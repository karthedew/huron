"""Verification of ID tokens issued by the institutional OIDC provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import jwt

from huron.core.security.broker.tokens import TokenInvalid
from huron.pkg.errors import Unavailable

if TYPE_CHECKING:
    from huron.pkg.clock import Clock

__all__ = ["CompanyIdentity", "CompanyTokenVerifier"]

_ALGORITHMS = ["RS256", "ES256"]
_REFRESH_INTERVAL = timedelta(minutes=1)
_LEEWAY = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class CompanyIdentity:
    """Who the company token says the user is."""

    subject: str
    username: str
    display_name: str


class CompanyTokenVerifier:
    """Verifies company ID tokens against the issuer's published keys.

    The discovery document and the JWKS are fetched on first use and cached; an unknown ``kid``
    refreshes the JWKS at most once a minute.
    """

    def __init__(self, http: httpx.AsyncClient, issuer: str, audience: str, clock: Clock) -> None:
        self._http = http
        self._issuer = issuer
        self._audience = audience
        self._clock = clock
        self._jwks_uri: str | None = None
        self._keys: dict[str, Any] = {}
        self._fetched_at: datetime | None = None

    async def verify(self, token: str) -> CompanyIdentity:
        """Return the identity in a valid company token; raises ``TokenInvalid`` otherwise."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise TokenInvalid("company token is not a JWT") from error
        if header.get("alg") not in _ALGORITHMS:
            raise TokenInvalid("company token algorithm is not accepted")
        key = await self._key(str(header.get("kid", "")))
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"verify_exp": False, "verify_iat": False, "require": ["sub", "exp"]},
            )
        except jwt.PyJWTError as error:
            raise TokenInvalid(f"company token rejected: {error}") from error
        if datetime.fromtimestamp(payload["exp"], UTC) + _LEEWAY <= self._clock.now():
            raise TokenInvalid("company token has expired")
        return _identity(payload)

    async def _key(self, kid: str) -> Any:
        if kid not in self._keys and self._may_refresh():
            await self._refresh()
        if kid not in self._keys:
            raise TokenInvalid("company token was signed by an unknown key")
        return self._keys[kid]

    def _may_refresh(self) -> bool:
        return self._fetched_at is None or self._clock.now() - self._fetched_at >= _REFRESH_INTERVAL

    async def _refresh(self) -> None:
        if self._jwks_uri is None:
            discovery = await self._get_json(
                f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
            )
            self._jwks_uri = str(discovery["jwks_uri"])
        jwks = await self._get_json(self._jwks_uri)
        self._keys = {
            str(entry["kid"]): jwt.PyJWK(entry).key
            for entry in jwks.get("keys", [])
            if "kid" in entry
        }
        self._fetched_at = self._clock.now()

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise Unavailable(
                "the company identity provider is unreachable", {"url": url}
            ) from error
        return document


def _identity(payload: dict[str, Any]) -> CompanyIdentity:
    subject = str(payload["sub"])
    username = str(payload.get("preferred_username") or subject)
    name = str(payload.get("name") or username)
    return CompanyIdentity(subject, username, name)
