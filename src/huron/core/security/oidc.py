"""OIDC bearer-token resolution and the browser login code flow.

Two ways in from one identity provider. A programmatic caller presents a
token as a bearer credential, which :class:`JwksVerifier` validates against
the provider's published keys and :class:`OidcResolver` maps to a
:class:`Principal`. A browser goes through the authorization-code flow
with PKCE, driven by :class:`OidcClient`, with the pending-login state
riding in a signed :class:`LoginFlow` cookie between the start redirect
and the callback rather than in server-side storage. Both paths read the
same claims: ``sub`` names the subject and a configurable groups claim
supplies the groups, an absent claim resolving to an empty set.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

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
    """What the callback hands the service: enough to upsert a principal.

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
    """Discovery plus the authorization-code flow for one configured provider.

    Holds the client credentials and the redirect URL registered with the
    provider, and builds its own :class:`JwksVerifier` with the client id
    as audience, which is what an ID token is issued for. The flow is
    always PKCE (``S256``) with a nonce: the caller keeps ``state``,
    ``nonce`` and the code verifier across the redirect (see
    :class:`LoginFlow`) and hands them back to :meth:`exchange_code`.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        provider: OidcProviderConfig,
        *,
        client_id: str,
        client_secret: str,
        redirect_url: str,
        scopes: tuple[str, ...] = ("openid", "profile", "email"),
        groups_claim: str = "groups",
    ) -> None:
        """Build a client for an already-discovered provider.

        Args:
            http: The async HTTP client used for the token exchange; the
                caller owns its lifetime.
            provider: The provider's endpoints, usually from
                :meth:`discover`.
            client_id: The client id registered with the provider; also
                the audience ID tokens are verified against.
            client_secret: The matching secret, sent on the token
                exchange.
            redirect_url: The callback URL registered with the provider;
                it must match exactly on both legs of the flow.
            scopes: The scopes requested at authorization; ``openid`` is
                what makes the provider issue an ID token at all.
            groups_claim: The ID-token claim carrying the user's groups.
        """
        self._http = http
        self._provider = provider
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_url = redirect_url
        self._scopes = scopes
        self._groups_claim = groups_claim
        self._verifier = JwksVerifier(
            issuer=provider.issuer, audience=client_id, jwks_url=provider.jwks_uri
        )

    @classmethod
    async def discover(
        cls,
        http: httpx.AsyncClient,
        issuer: str,
        *,
        client_id: str,
        client_secret: str,
        redirect_url: str,
        scopes: tuple[str, ...] = ("openid", "profile", "email"),
        groups_claim: str = "groups",
    ) -> OidcClient:
        """Fetch ``{issuer}/.well-known/openid-configuration`` and build a client.

        The well-known path is appended to ``issuer`` verbatim, and the
        document's ``issuer`` field must equal it exactly - a provider
        that serves a different issuer's document (a misconfigured proxy,
        or a copy-pasted well-known URL) is refused rather than silently
        trusted.

        Args:
            http: The async HTTP client used for discovery and, afterwards,
                the token exchange; the caller owns its lifetime.
            issuer: The provider's issuer URL.
            client_id: The client id registered with the provider; also
                the audience ID tokens are verified against.
            client_secret: The matching secret, sent on the token
                exchange.
            redirect_url: The callback URL registered with the provider.
            scopes: The scopes requested at authorization.
            groups_claim: The ID-token claim carrying the user's groups.

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
        return cls(
            http,
            provider,
            client_id=client_id,
            client_secret=client_secret,
            redirect_url=redirect_url,
            scopes=scopes,
            groups_claim=groups_claim,
        )

    @property
    def provider(self) -> OidcProviderConfig:
        """The discovered provider document.

        The composition root needs the JWKS endpoint to build the
        bearer-token verifier alongside this client's own code-flow one.
        """
        return self._provider

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        """Build the URL the browser is redirected to for the authorization leg.

        Args:
            state: The opaque value the provider echoes back on the
                callback, so the callback can be matched to the flow that
                started it.
            nonce: The value the provider binds into the ID token, which
                :meth:`exchange_code` checks.
            code_challenge: The ``S256`` challenge for the flow's code
                verifier, from :func:`code_challenge_s256`.

        Returns:
            The provider's authorization endpoint with the ``code``
            response type, the client id, redirect URL, scopes, ``state``,
            ``nonce`` and PKCE parameters as its query string.
        """
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_url,
            "scope": " ".join(self._scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._provider.authorization_endpoint}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> OidcUser:
        """Exchange the callback's authorization code for a verified user.

        POST the token endpoint, then verify the ID token (sig, iss, aud,
        exp via JwksVerifier; nonce here) and map claims to OidcUser. The
        verifier's own rejection propagates as the same error type, so
        the callback treats every failure on this leg alike.

        Args:
            code: The authorization code the provider sent to the
                callback.
            code_verifier: The PKCE verifier whose challenge started the
                flow; the provider refuses the exchange if they do not
                match.
            nonce: The nonce the flow started with; must equal the ID
                token's ``nonce`` claim.

        Returns:
            The verified identity, ready for the principal store's upsert.

        Raises:
            AuthError: If the token endpoint returns an error status, the
                response carries no ``id_token``, or the token's nonce is
                not the one this flow started with.
        """
        response = await self._http.post(
            self._provider.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_url,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code_verifier": code_verifier,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise AuthError(f"OIDC token exchange failed: {error}") from error
        id_token = response.json().get("id_token")
        if not isinstance(id_token, str):
            raise AuthError("OIDC token response is missing an id_token")
        claims = self._verifier(id_token)
        if claims.get("nonce") != nonce:
            raise AuthError("OIDC token nonce mismatch")
        return self._map_claims(claims)

    def _map_claims(self, claims: Mapping[str, object]) -> OidcUser:
        """Map verified ID-token claims to an :class:`OidcUser`, tolerating optional ones.

        Only ``sub`` is mandatory. ``name`` falls back to the subject,
        ``email`` to None, and the groups claim to an empty set when it is
        missing or is not a list of strings - a malformed groups claim is
        treated like an absent one rather than refusing the login.

        Args:
            claims: The claims :class:`JwksVerifier` returned.

        Returns:
            The user as the principal store's upsert expects it.

        Raises:
            AuthError: If ``sub`` is missing or not a string.
        """
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise AuthError("OIDC token is missing a subject claim")
        display_name = claims.get("name")
        if not isinstance(display_name, str):
            display_name = subject
        email = claims.get("email")
        if not isinstance(email, str):
            email = None
        raw_groups = claims.get(self._groups_claim, [])
        if not isinstance(raw_groups, list) or not all(isinstance(g, str) for g in raw_groups):
            raw_groups = []
        return OidcUser(
            idp_subject=subject,
            display_name=display_name,
            email=email,
            groups=frozenset(raw_groups),
        )


def code_challenge_s256(code_verifier: str) -> str:
    """Derive the RFC 7636 ``S256`` PKCE code challenge for the given verifier.

    Args:
        code_verifier: The high-entropy ASCII verifier the flow keeps to
            itself until the token exchange.

    Returns:
        The unpadded URL-safe base64 of the verifier's SHA-256, as the
        ``code_challenge`` parameter expects it.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


_SIGNATURE_LENGTH = hashlib.sha256().digest_size


def _split_signed_payload(raw: bytes) -> tuple[bytes, bytes] | None:
    """Split ``payload + b"." + signature`` without ambiguity from stray dots.

    The signature is a fixed-length SHA-256 digest, so the separator is
    found by counting back from the end rather than by searching for a
    dot - the JSON payload may contain dots and so may the raw digest
    bytes.

    Args:
        raw: The base64-decoded cookie bytes.

    Returns:
        The payload and the signature, or None if ``raw`` is too short to
        hold both or the byte before the signature is not a dot.
    """
    if len(raw) < _SIGNATURE_LENGTH + 2:
        return None
    separator_index = len(raw) - _SIGNATURE_LENGTH - 1
    if raw[separator_index : separator_index + 1] != b".":
        return None
    return raw[:separator_index], raw[separator_index + 1 :]


@dataclass(frozen=True, slots=True)
class LoginFlow:
    """Pending-login state for one browser's OIDC login.

    Carried in an HMAC-signed cookie between ``/auth/oidc/start`` and the
    callback - there is no server-side storage for it. The cookie is
    signed, not encrypted: ``state``, ``nonce`` and ``code_verifier`` are
    only useful to whoever can also produce a valid signature, and
    ``issued_at`` bounds how long a flow stays usable. ``return_to`` is
    the path to land on after login and is validated at construction to
    be a local path, so a decoded cookie can never send the browser
    off-site.
    """

    state: str
    nonce: str
    code_verifier: str
    issued_at: int
    return_to: str  # path-only; validated to start with "/" and not "//"

    def __post_init__(self) -> None:
        """Refuse a ``return_to`` that is not a local path.

        Raises:
            AuthError: If ``return_to`` does not start with ``/``, or
                starts with ``//`` and would therefore be read as a
                scheme-relative URL.
        """
        if not self.return_to.startswith("/") or self.return_to.startswith("//"):
            raise AuthError("login flow return_to must be a local path")

    @classmethod
    def new(cls, *, return_to: str = "/", now: datetime | None = None) -> LoginFlow:
        """Start a flow with fresh random state, nonce and PKCE verifier.

        Args:
            return_to: The local path to land on after login; the app
                root when omitted.
            now: The instant recorded as ``issued_at``, for deterministic
                tests; the current UTC time when omitted.

        Returns:
            A flow whose ``state`` and ``nonce`` are 24-byte and whose
            ``code_verifier`` is a 64-byte URL-safe random token.
        """
        moment = now or datetime.now(UTC)
        return cls(
            state=secrets.token_urlsafe(24),
            nonce=secrets.token_urlsafe(24),
            code_verifier=secrets.token_urlsafe(64),
            issued_at=int(moment.timestamp()),
            return_to=return_to,
        )

    def encode(self, secret: bytes) -> str:
        """Serialize the flow as a signed, URL-safe cookie value.

        The payload is compact JSON of every field, followed by a dot and
        the HMAC-SHA256 of that payload under ``secret``, the whole
        URL-safe base64 encoded.

        Args:
            secret: The service's login-flow signing key; the same key
                must be used to decode.

        Returns:
            The cookie value.
        """
        payload = json.dumps(dataclasses.asdict(self), separators=(",", ":")).encode()
        signature = hmac.new(secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode()

    @classmethod
    def decode(
        cls, value: str, secret: bytes, *, max_age: int = 600, now: datetime | None = None
    ) -> LoginFlow:
        """Decode a cookie value back into a flow, refusing anything untrustworthy.

        Reject bad signatures and flows older than ``max_age`` seconds.
        The signature is checked before the payload is parsed, so a
        forged cookie never reaches the JSON decoder, and a flow stamped
        in the future is rejected too, since this service cannot have
        issued it. ``max_age`` should equal the cookie's own lifetime, so
        a flow the browser still holds is never rejected as stale and one
        it has forgotten is never accepted. A payload whose ``return_to``
        is not a local path is refused by construction.

        Args:
            value: The cookie value as the browser returned it.
            secret: The signing key :meth:`encode` used.
            max_age: How many seconds after ``issued_at`` a flow remains
                usable.
            now: The instant age is judged against, for deterministic
                tests; the current UTC time when omitted.

        Returns:
            The flow exactly as it was encoded.

        Raises:
            AuthError: If the value is not valid base64, is too short or
                lacks the separator, fails the signature check, is not a
                well-formed payload, or was issued more than ``max_age``
                seconds ago or in the future.
        """
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii"))
        except ValueError as error:
            raise AuthError("invalid login flow encoding") from error
        split = _split_signed_payload(raw)
        if split is None:
            raise AuthError("invalid login flow encoding")
        payload, signature = split
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            raise AuthError("invalid login flow signature")
        try:
            flow = cls(**json.loads(payload))
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as error:
            raise AuthError("invalid login flow payload") from error
        moment = now or datetime.now(UTC)
        age = int(moment.timestamp()) - flow.issued_at
        if age < 0 or age > max_age:
            raise AuthError("login flow has expired")
        return flow


__all__ = [
    "JwksVerifier",
    "LoginFlow",
    "OidcClient",
    "OidcProviderConfig",
    "OidcResolver",
    "OidcUser",
    "code_challenge_s256",
]
