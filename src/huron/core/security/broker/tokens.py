"""Huron-signed JWTs: claims, issuer and verifier."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import jwt

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from collections.abc import Iterable

    from huron.core.security.broker.keys import KeyRing
    from huron.pkg.clock import Clock

__all__ = ["HuronClaims", "TokenInvalid", "TokenIssuer", "TokenVerifier"]

TOKEN_INVALID = register("TOKEN_INVALID", 401, "Token invalid")

_REQUIRED = ("sub", "name", "groups", "iss", "aud", "iat", "exp", "jti")


class TokenInvalid(HuronError):
    """A token that is not a valid, current Huron token."""

    error_code = TOKEN_INVALID


@dataclass(frozen=True, slots=True)
class HuronClaims:
    """The claims of a Huron token."""

    sub: str
    name: str
    groups: tuple[str, ...]
    iss: str
    aud: str
    iat: datetime
    exp: datetime
    jti: str

    def as_payload(self) -> dict[str, Any]:
        """Render as a JWT payload."""
        return {
            "sub": self.sub,
            "name": self.name,
            "groups": list(self.groups),
            "iss": self.iss,
            "aud": self.aud,
            "iat": int(self.iat.timestamp()),
            "exp": int(self.exp.timestamp()),
            "jti": self.jti,
        }


class TokenIssuer:
    """Signs Huron tokens with the current key of a key ring."""

    def __init__(
        self, ring: KeyRing, clock: Clock, issuer: str, audience: str, ttl: timedelta
    ) -> None:
        self._ring = ring
        self._clock = clock
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl

    def issue(self, subject: str, name: str, groups: Iterable[str]) -> tuple[str, HuronClaims]:
        """Return a signed token and its claims."""
        now = self._clock.now().replace(microsecond=0)
        claims = HuronClaims(
            sub=subject,
            name=name,
            groups=tuple(sorted(set(groups))),
            iss=self._issuer,
            aud=self._audience,
            iat=now,
            exp=now + self._ttl,
            jti=str(uuid.uuid4()),
        )
        key = self._ring.current
        token = jwt.encode(
            claims.as_payload(), key.private_pem, algorithm="ES256", headers={"kid": key.kid}
        )
        return token, claims


class TokenVerifier:
    """Verifies Huron tokens against the key ring and the configured issuer and audience."""

    def __init__(self, ring: KeyRing, issuer: str, audience: str, clock: Clock) -> None:
        self._ring = ring
        self._issuer = issuer
        self._audience = audience
        self._clock = clock

    def verify(self, token: str) -> HuronClaims:
        """Return the claims of a valid token; raises :class:`TokenInvalid` otherwise."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise TokenInvalid("token is not a JWT") from error
        if header.get("alg") != "ES256":
            raise TokenInvalid("token algorithm is not ES256")
        key = self._ring.find(str(header.get("kid", "")))
        if key is None:
            raise TokenInvalid("token was signed by an unknown key")
        try:
            payload = jwt.decode(
                token,
                jwt.PyJWK(key.public_jwk).key,
                algorithms=["ES256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"verify_exp": False, "verify_iat": False, "require": list(_REQUIRED)},
            )
        except jwt.PyJWTError as error:
            raise TokenInvalid(f"token rejected: {error}") from error
        return self._claims(payload)

    def _claims(self, payload: dict[str, Any]) -> HuronClaims:
        expires = datetime.fromtimestamp(payload["exp"], UTC)
        if expires <= self._clock.now():
            raise TokenInvalid("token has expired")
        groups = payload["groups"]
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise TokenInvalid("token groups claim is malformed")
        return HuronClaims(
            sub=str(payload["sub"]),
            name=str(payload["name"]),
            groups=tuple(groups),
            iss=str(payload["iss"]),
            aud=str(payload["aud"]),
            iat=datetime.fromtimestamp(payload["iat"], UTC),
            exp=expires,
            jti=str(payload["jti"]),
        )
