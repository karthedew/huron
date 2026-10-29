"""ES256 signing keys and the key ring that issues and verifies Huron tokens."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime, timedelta

    from huron.pkg.clock import Clock

__all__ = ["KeyRing", "KeyStore", "SigningKey", "generate_key", "thumbprint"]


@dataclass(frozen=True, slots=True)
class SigningKey:
    """One ES256 key pair; ``retired_at`` is set once a newer key replaced it."""

    kid: str
    private_pem: str
    public_jwk: dict[str, Any]
    created_at: datetime
    retired_at: datetime | None = None

    def retire(self, at: datetime) -> SigningKey:
        """Return the key marked retired at ``at``."""
        return replace(self, retired_at=at)


class KeyStore(Protocol):
    """Persists signing keys."""

    async def list_keys(self) -> Sequence[SigningKey]:
        """Every key, newest first."""
        ...

    async def insert_key(self, key: SigningKey) -> None:
        """Store a new key."""
        ...

    async def retire_key(self, kid: str, at: datetime) -> None:
        """Mark a key retired."""
        ...


def generate_key(clock: Clock) -> SigningKey:
    """Generate a new P-256 key whose ``kid`` is derived from its public JWK thumbprint."""
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    jwk: dict[str, Any] = json.loads(ECAlgorithm.to_jwk(private.public_key()))
    kid = thumbprint(jwk)[:16]
    jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
    return SigningKey(kid, pem, jwk, clock.now())


def thumbprint(jwk: dict[str, Any]) -> str:
    """The RFC 7638 SHA-256 thumbprint of an EC public JWK, as lowercase hex."""
    members = {name: jwk[name] for name in ("crv", "kty", "x", "y")}
    canonical = json.dumps(members, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


class KeyRing:
    """The keys in use: the current signing key and every key still accepted for verification."""

    def __init__(self, keys: Iterable[SigningKey], overlap: timedelta, clock: Clock) -> None:
        self._keys = sorted(keys, key=lambda key: key.created_at, reverse=True)
        self._overlap = overlap
        self._clock = clock

    @property
    def current(self) -> SigningKey:
        """The newest key that is not retired."""
        for key in self._keys:
            if key.retired_at is None:
                return key
        raise LookupError("the key ring has no current signing key")

    def verification_keys(self) -> list[SigningKey]:
        """Keys whose signatures are accepted: active ones and those retired within the overlap."""
        now = self._clock.now()
        return [
            key
            for key in self._keys
            if key.retired_at is None or now - key.retired_at <= self._overlap
        ]

    def find(self, kid: str) -> SigningKey | None:
        """The verification key with ``kid``, if accepted."""
        return next((key for key in self.verification_keys() if key.kid == kid), None)

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """The public JSON Web Key Set."""
        return {"keys": [dict(key.public_jwk) for key in self.verification_keys()]}
