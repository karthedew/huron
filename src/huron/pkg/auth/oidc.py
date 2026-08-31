"""OIDC bearer-token resolution and the browser login code flow."""

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

from .errors import AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class OidcResolver:
    """Resolve a token after an injected verifier has validated its signature."""

    def __init__(
        self,
        verify: Callable[[str], Mapping[str, object]],
        *,
        subject_claim: str = "sub",
        groups_claim: str = "groups",
    ):
        self.verify = verify
        self.subject_claim = subject_claim
        self.groups_claim = groups_claim

    async def resolve(self, credential: str) -> Principal:
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
    """Validate signature, issuer, audience, and expiry against the IdP's JWKS."""

    def __init__(self, *, issuer: str, audience: str, jwks_url: str) -> None:
        self.issuer = issuer
        self.audience = audience
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    def __call__(self, token: str) -> Mapping[str, object]:
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
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


@dataclass(frozen=True, slots=True)
class OidcUser:
    """What the callback hands the service: enough to upsert a principal."""

    idp_subject: str
    display_name: str
    email: str | None
    groups: frozenset[str]


class OidcClient:
    """Discovery plus the authorization-code flow for one configured provider."""

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
        """Fetch ``{issuer}/.well-known/openid-configuration`` and build a client."""
        response = await http.get(f"{issuer}/.well-known/openid-configuration")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise AuthError(f"OIDC discovery failed for issuer {issuer!r}: {error}") from error
        document = response.json()
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
        """The discovered provider document - the composition root needs the
        JWKS endpoint to build the bearer-token verifier alongside this
        client's own code-flow one."""
        return self._provider

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
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
        """POST the token endpoint, then verify the ID token (sig, iss, aud,
        exp via JwksVerifier; nonce here) and map claims to OidcUser."""
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
    """RFC 7636 ``S256`` PKCE code challenge for the given verifier."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


_SIGNATURE_LENGTH = hashlib.sha256().digest_size


def _split_signed_payload(raw: bytes) -> tuple[bytes, bytes] | None:
    """Split ``payload + b"." + signature`` without ambiguity from stray dots."""
    if len(raw) < _SIGNATURE_LENGTH + 2:
        return None
    separator_index = len(raw) - _SIGNATURE_LENGTH - 1
    if raw[separator_index : separator_index + 1] != b".":
        return None
    return raw[:separator_index], raw[separator_index + 1 :]


@dataclass(frozen=True, slots=True)
class LoginFlow:
    """Pending-login state, carried in an HMAC-signed cookie between
    ``/auth/oidc/start`` and the callback - there is no server-side storage
    for it."""

    state: str
    nonce: str
    code_verifier: str
    issued_at: int
    return_to: str  # path-only; validated to start with "/" and not "//"

    def __post_init__(self) -> None:
        if not self.return_to.startswith("/") or self.return_to.startswith("//"):
            raise AuthError("login flow return_to must be a local path")

    @classmethod
    def new(cls, *, return_to: str = "/", now: datetime | None = None) -> LoginFlow:
        moment = now or datetime.now(UTC)
        return cls(
            state=secrets.token_urlsafe(24),
            nonce=secrets.token_urlsafe(24),
            code_verifier=secrets.token_urlsafe(64),
            issued_at=int(moment.timestamp()),
            return_to=return_to,
        )

    def encode(self, secret: bytes) -> str:
        payload = json.dumps(dataclasses.asdict(self), separators=(",", ":")).encode()
        signature = hmac.new(secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + b"." + signature).decode()

    @classmethod
    def decode(
        cls, value: str, secret: bytes, *, max_age: int = 600, now: datetime | None = None
    ) -> LoginFlow:
        """Reject bad signatures and flows older than ``max_age`` seconds."""
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
