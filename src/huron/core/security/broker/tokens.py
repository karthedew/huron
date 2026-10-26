"""Signed lake identity claims with clock-controlled validity checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

import jwt

from huron.core.foundation.errors import AuthError
from huron.core.security.broker.keys import TOKEN_TTL_MAX, VERIFY_LEEWAY
from huron.core.security.broker.ladder import ClaimedRole

if TYPE_CHECKING:
    from collections.abc import Mapping

    from huron.core.foundation.clock import Clock
    from huron.core.security.broker.keys import HuronKeys, KeyRing, PublicSigningKey
    from huron.core.security.broker.ladder import Grants

HURON_API_AUDIENCE: Final = "huron-api"


@dataclass(frozen=True, slots=True)
class HuronClaims:
    """Verified identity and informational roles, never request-time authority."""

    iss: str
    sub: str
    aud: tuple[str, ...]
    roles: tuple[ClaimedRole, ...]
    groups: tuple[str, ...]
    iat: datetime
    exp: datetime
    kid: str


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A compact signature and the exact claims it carries."""

    token: str
    claims: HuronClaims


def _issuer(issuer: str) -> None:
    parsed = urlsplit(issuer)
    if issuer.endswith("/") or parsed.query or parsed.fragment or "?" in issuer or "#" in issuer:
        raise ValueError("issuer must have no trailing slash, query or fragment")


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must be an array of non-empty strings")
    return tuple(value)


def _validate_times(
    payload: Mapping[str, object], now: datetime, *, maximum_lifetime: timedelta | None = None
) -> tuple[datetime, datetime]:
    """Check NumericDates against one clock reading.

    Args:
        payload: Signed claims carrying iat and exp.
        now: Injected validation instant.
        maximum_lifetime: Optional upper bound for the lifetime.

    Returns:
        UTC issuance and expiration instants.

    Raises:
        ValueError: If dates, validity or lifetime are invalid.
    """
    issued, expires = payload["iat"], payload["exp"]
    if type(issued) is not int or type(expires) is not int:
        raise ValueError("iat and exp must be integer NumericDates")
    seconds = now.timestamp()
    leeway = VERIFY_LEEWAY.total_seconds()
    if issued > seconds + leeway or seconds >= expires + leeway:
        raise ValueError("token is outside its validity interval")
    if expires <= issued or (
        maximum_lifetime is not None and expires - issued > maximum_lifetime.total_seconds()
    ):
        raise ValueError("token lifetime is invalid")
    try:
        return datetime.fromtimestamp(issued, UTC), datetime.fromtimestamp(expires, UTC)
    except (OverflowError, OSError) as exc:
        raise ValueError("NumericDate is outside the supported range") from exc


def _claims(payload: Mapping[str, object], kid: str, now: datetime, issuer: str) -> HuronClaims:
    issued, expires = _validate_times(payload, now, maximum_lifetime=TOKEN_TTL_MAX)
    subject = payload["sub"]
    if not isinstance(subject, str) or not subject:
        raise ValueError("sub must be a non-empty string")
    audience = _strings(payload["aud"], "aud")
    groups = _strings(payload["groups"], "groups")
    roles = tuple(ClaimedRole.parse(role) for role in _strings(payload["roles"], "roles"))
    return HuronClaims(issuer, subject, audience, roles, groups, issued, expires, kid)


class HuronTokenIssuer:
    """Mint tokens from an already loaded signing ring without persistence access."""

    def __init__(
        self,
        keys: HuronKeys,
        *,
        issuer: str,
        audience: tuple[str, ...],
        ttl: timedelta,
        clock: Clock,
    ) -> None:
        """Capture issuer policy and injected signing material.

        Args:
            keys: Refreshed signing material.
            issuer: Exact token issuer URL.
            audience: Intended services, including the Huron API.
            ttl: Lifetime between one minute and one hour.
            clock: Source of issuance time.

        Raises:
            ValueError: If issuer, audience or lifetime violates the token contract.
        """
        _issuer(issuer)
        if HURON_API_AUDIENCE not in audience or any(
            not isinstance(a, str) or not a for a in audience
        ):
            raise ValueError("audience must contain huron-api and only non-empty strings")
        if not timedelta(seconds=60) <= ttl <= TOKEN_TTL_MAX:
            raise ValueError("ttl must be between 60 and 3600 seconds")
        self._keys, self._issuer, self._audience = keys, issuer, audience
        self._ttl, self._clock = ttl, clock

    def issue(self, subject: str, groups: frozenset[str], grants: Grants) -> IssuedToken:
        """Sign normalized identity and informational grants.

        Args:
            subject: Resolved company username.
            groups: Directory memberships.
            grants: Current grants to expose as informational roles.

        Returns:
            Signed token and its exact claims.

        Raises:
            ValueError: If the subject or a group name is empty.
        """
        if not subject or any(not group for group in groups):
            raise ValueError("subject and group names must be non-empty")
        now = self._clock.now()
        record, private = self._keys.ring.signer(now)
        issued = math.floor(now.timestamp())
        payload = {
            "iss": self._issuer,
            "sub": subject,
            "aud": list(self._audience),
            "iat": issued,
            "exp": issued + math.floor(self._ttl.total_seconds()),
            "groups": sorted(groups),
            "roles": [str(ClaimedRole.of(grant)) for grant in grants],
        }
        token = jwt.encode(
            payload, private, algorithm=record.key.alg, headers={"kid": record.key.kid}
        )
        return IssuedToken(token, _claims(payload, record.key.kid, now, self._issuer))


def _verification_key(ring: KeyRing, token: str, now: datetime) -> PublicSigningKey:
    kid = jwt.get_unverified_header(token)["kid"]
    if not isinstance(kid, str) or not kid:
        raise ValueError("kid must be a non-empty string")
    key = ring.verification_key(kid, now)
    if key is None:
        raise ValueError("unknown or retired signing key")
    return key


class HuronTokenVerifier:
    """Verify signatures before interpreting identity, using only a ring snapshot."""

    def __init__(self, keys: HuronKeys, *, issuer: str, clock: Clock) -> None:
        """Capture the trusted issuer, ring and clock.

        Args:
            keys: Refreshed verification material.
            issuer: Exact trusted issuer.
            clock: Source of validation time.
        """
        _issuer(issuer)
        self._keys, self._issuer, self._clock = keys, issuer, clock

    def verify(self, token: str) -> HuronClaims:
        """Validate a compact token and return its immutable identity claims.

        Args:
            token: Compact signed JWT.

        Returns:
            Signature-verified, shape-checked claims.

        Raises:
            AuthError: If any header, signature, claim or validity rule fails.
        """
        now, ring = self._clock.now(), self._keys.ring
        try:
            key = _verification_key(ring, token, now)
            payload = jwt.decode(
                token,
                jwt.PyJWK.from_dict(key.as_jwk()).key,
                algorithms=[key.alg],
                issuer=self._issuer,
                audience=HURON_API_AUDIENCE,
                options={
                    "require": ["iss", "sub", "aud", "iat", "exp"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_jti": False,
                    "verify_sub": False,
                },
            )
            return _claims(payload, key.kid, now, self._issuer)
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise AuthError(str(exc)) from exc
