"""Immutable signing-key snapshots and publication-aware rotation rules."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol, Self

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from huron.core.security.errors import RotationRefused, SigningKeyUnavailable

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from huron.core.foundation.clock import Clock


type SigningAlgorithm = Literal["ES256", "RS256"]
type PrivateSigningKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey

TOKEN_TTL_MAX: Final = timedelta(hours=1)
VERIFY_LEEWAY: Final = timedelta(seconds=30)
RETENTION: Final = TOKEN_TTL_MAX + VERIFY_LEEWAY
REFRESH_INTERVAL: Final = timedelta(seconds=60)
MAX_RING_AGE: Final = timedelta(minutes=5)
JWKS_MAX_AGE: Final = timedelta(minutes=5)
MIN_PUBLICATION_LEAD: Final = timedelta(minutes=10)


def _required_members(members: Mapping[str, str]) -> dict[str, str]:
    """Select the public members that identify a supported key.

    Args:
        members: JWK members, possibly including optional metadata.

    Returns:
        Only the required public EC or RSA members.

    Raises:
        ValueError: If the key type is unsupported.
    """
    names: tuple[str, ...]
    match members["kty"]:
        case "EC":
            names = ("crv", "kty", "x", "y")
        case "RSA":
            names = ("e", "kty", "n")
        case _:
            raise ValueError("Unsupported signing key type")
    return {name: members[name] for name in names}


def jwk_thumbprint(members: Mapping[str, str]) -> str:
    """Return the RFC 7638 SHA-256 public-key thumbprint.

    Args:
        members: JWK members for an EC or RSA key.

    Returns:
        The unpadded base64url digest of the canonical required members.
    """
    canonical = json.dumps(_required_members(members), sort_keys=True, separators=(",", ":"))
    return (
        base64.urlsafe_b64encode(hashlib.sha256(canonical.encode("utf-8")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


@dataclass(frozen=True, slots=True)
class PublicSigningKey:
    """A public key whose required JWK members are owned by this value."""

    kid: str
    alg: SigningAlgorithm
    members: Mapping[str, str]

    def __post_init__(self) -> None:
        """Detach the public members from the caller's mutable mapping."""
        object.__setattr__(self, "members", MappingProxyType(_required_members(self.members)))

    @classmethod
    def from_private(cls, key: PrivateSigningKey) -> PublicSigningKey:
        """Derive the supported algorithm, public members and stable identifier.

        Args:
            key: A P-256 or at least 2048-bit RSA private key.

        Returns:
            The corresponding public signing-key value.

        Raises:
            ValueError: If the key type, curve or size is unsupported.
        """
        alg: SigningAlgorithm
        if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
            alg = "ES256"
            members = ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
        elif isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 2048:
            alg = "RS256"
            members = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        else:
            raise ValueError("Signing requires P-256 or RSA with at least 2048 bits")
        return cls(jwk_thumbprint(members), alg, members)

    def as_jwk(self) -> dict[str, str]:
        """Render a detached public JWK with its signing metadata.

        Returns:
            Public members plus kid, algorithm and signing use.
        """
        return {**self.members, "kid": self.kid, "alg": self.alg, "use": "sig"}


class KeyState(StrEnum):
    """A key's derived signing and verification lifetime."""

    PENDING = "pending"
    ACTIVE = "active"
    RETIRING = "retiring"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class SigningKeyRecord:
    """A registered key and its half-open signing interval."""

    key: PublicSigningKey
    private_ref: str
    active_from: datetime
    retired_at: datetime | None

    def state(self, at: datetime) -> KeyState:
        """Determine the lifecycle state at an instant.

        Args:
            at: The instant to evaluate.

        Returns:
            Pending, active, retiring or retired, including retention.
        """
        if at < self.active_from:
            return KeyState.PENDING
        if self.retired_at is None or at < self.retired_at:
            return KeyState.ACTIVE
        if at < self.retired_at + RETENTION:
            return KeyState.RETIRING
        return KeyState.RETIRED


@dataclass(frozen=True, slots=True)
class KeyRing:
    """A time-indexed key snapshot, independent of its source containers."""

    records: tuple[SigningKeyRecord, ...]
    private_keys: Mapping[str, PrivateSigningKey] = field(repr=False)
    loaded_at: datetime

    def __post_init__(self) -> None:
        """Own ordered records and a read-only copy of the loaded-key mapping."""
        object.__setattr__(
            self, "records", tuple(sorted(self.records, key=lambda row: row.active_from))
        )
        object.__setattr__(self, "private_keys", MappingProxyType(dict(self.private_keys)))

    def signer(self, at: datetime) -> tuple[SigningKeyRecord, PrivateSigningKey]:
        """Select the active loaded signer from a sufficiently fresh snapshot.

        Args:
            at: The signing instant.

        Returns:
            The active record and its private signing key.

        Raises:
            SigningKeyUnavailable: If stale, without an active key or without its private key.
        """
        if at - self.loaded_at > MAX_RING_AGE:
            raise SigningKeyUnavailable(context={"reason": "stale"})
        record = next((row for row in self.records if row.state(at) == KeyState.ACTIVE), None)
        if record is None:
            raise SigningKeyUnavailable(context={"reason": "no_active_key"})
        private = self.private_keys.get(record.key.kid)
        if private is None:
            raise SigningKeyUnavailable(context={"reason": "not_loaded", "kid": record.key.kid})
        return record, private

    def verification_key(self, kid: str, at: datetime) -> PublicSigningKey | None:
        """Find a published key, regardless of snapshot age or private-key availability.

        Args:
            kid: The thumbprint to look up.
            at: The verification instant.

        Returns:
            The public key unless absent or retired.
        """
        return next(
            (
                row.key
                for row in self.records
                if row.key.kid == kid and row.state(at) != KeyState.RETIRED
            ),
            None,
        )

    def jwks(self, at: datetime) -> dict[str, list[dict[str, str]]]:
        """Render all published keys in activation order.

        Args:
            at: The publication instant.

        Returns:
            A JWKS containing pending, active and retiring public keys.
        """
        return {
            "keys": [row.key.as_jwk() for row in self.records if row.state(at) != KeyState.RETIRED]
        }

    def algorithms(self, at: datetime) -> tuple[SigningAlgorithm, ...]:
        """List distinct published algorithms in sorted order.

        Args:
            at: The publication instant.

        Returns:
            The algorithms of non-retired keys.
        """
        return tuple(
            sorted({row.key.alg for row in self.records if row.state(at) != KeyState.RETIRED})
        )


@dataclass(frozen=True, slots=True)
class Rotation:
    """A successor insertion and the simultaneous retirement of the current tail."""

    retire_kid: str
    retired_at: datetime
    insert: SigningKeyRecord


def plan_rotation(
    ring: KeyRing, key: PublicSigningKey, private_ref: str, active_from: datetime, at: datetime
) -> Rotation:
    """Plan a contiguous rotation after enough time to publish its successor.

    Args:
        ring: The existing registered keys.
        key: The proposed successor's public key.
        private_ref: The successor's private-key reference.
        active_from: The requested switching instant.
        at: The planning instant.

    Returns:
        The current tail's retirement and the successor record to persist together.

    Raises:
        RotationRefused: If publication lead, tail state or key/reference uniqueness is invalid.
    """
    if active_from < at + MIN_PUBLICATION_LEAD:
        raise RotationRefused(context={"reason": "lead_too_short"})
    if not ring.records or ring.records[-1].state(at) != KeyState.ACTIVE:
        raise RotationRefused(context={"reason": "pending_key_exists"})
    if any(row.key.kid == key.kid or row.private_ref == private_ref for row in ring.records):
        raise RotationRefused(context={"reason": "key_already_registered"})
    return Rotation(
        ring.records[-1].key.kid, active_from, SigningKeyRecord(key, private_ref, active_from, None)
    )


def initial_record(key: PublicSigningKey, private_ref: str, at: datetime) -> SigningKeyRecord:
    """Build the first open-ended signing interval without a publication delay.

    Args:
        key: The bootstrap public key.
        private_ref: Its private-key reference.
        at: The instant signing begins.

    Returns:
        An active, open-ended record.
    """
    return SigningKeyRecord(key, private_ref, at, None)


class SigningKeySource(Protocol):
    """Resolve a registered reference without exposing private material to callers."""

    def load(self, private_ref: str) -> PrivateSigningKey:
        """Load a supported private key.

        Args:
            private_ref: The registered private-key reference.

        Returns:
            The private signing key.
        """
        ...


class FileSigningKeySource:
    """Read bounded, unencrypted PEM keys within one Secret-volume directory."""

    def __init__(self, directory: Path) -> None:
        """Keep the configured key directory.

        Args:
            directory: The directory containing key files and Secret-volume symlinks.
        """
        self._directory = directory

    def load(self, private_ref: str) -> PrivateSigningKey:
        """Resolve and read one bare filename without caching private material.

        Args:
            private_ref: An ASCII filename containing letters, digits, dots, underscores or hyphens.

        Returns:
            A supported private signing key.

        Raises:
            SigningKeyUnavailable: If the reference, containment, read or PEM validation fails.
        """
        if not re.fullmatch(r"[A-Za-z0-9._-]+", private_ref) or private_ref in {".", ".."}:
            raise SigningKeyUnavailable(context={"private_ref": private_ref, "reason": "bad_ref"})
        try:
            return self._decode(self._read(private_ref), private_ref)
        except FileNotFoundError:
            reason = "missing"
        except (OSError, RuntimeError):
            reason = "unreadable"
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            reasons: dict[type[Exception], str] = {
                TypeError: "encrypted",
                ValueError: "not_pem",
                UnsupportedAlgorithm: "unsupported_key",
            }
            reason = reasons.get(type(exc), "not_pem")
        raise SigningKeyUnavailable(context={"private_ref": private_ref, "reason": reason})

    @staticmethod
    def _decode(data: bytes, private_ref: str) -> PrivateSigningKey:
        """Parse PEM material and enforce the supported signing-key policy.

        Args:
            data: The bounded file contents.
            private_ref: The reference to report on refusal.

        Returns:
            A supported private key.

        Raises:
            SigningKeyUnavailable: If the parsed key is not supported for signing.
        """
        key = serialization.load_pem_private_key(data, password=None)
        if isinstance(key, (ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey)):
            try:
                PublicSigningKey.from_private(key)
            except ValueError:
                pass
            else:
                return key
        raise SigningKeyUnavailable(
            context={"private_ref": private_ref, "reason": "unsupported_key"}
        )

    def _read(self, private_ref: str) -> bytes:
        """Read no more than the PEM size limit from a contained resolved path.

        Args:
            private_ref: A validated bare filename.

        Returns:
            The file's bounded contents.

        Raises:
            SigningKeyUnavailable: If the path escapes the directory or exceeds the limit.
        """
        directory = self._directory.resolve()
        path = (directory / private_ref).resolve()
        if not path.is_relative_to(directory):
            raise SigningKeyUnavailable(
                context={"private_ref": private_ref, "reason": "outside_directory"}
            )
        if path.stat().st_size > 16 * 1024:
            raise SigningKeyUnavailable(context={"private_ref": private_ref, "reason": "not_pem"})
        with path.open("rb") as pem:
            return pem.read(16 * 1024)


class SigningKeyReader(Protocol):
    """Read registered keys whose verification retention has not ended."""

    async def unexpired(self, retired_after: datetime) -> tuple[SigningKeyRecord, ...]:
        """Read keys in activation order, propagating persistence failures.

        Args:
            retired_after: Exclusive lower bound for retirement, with open intervals included.

        Returns:
            The registered records in ascending activation order.
        """
        ...


class HuronKeys:
    """Own immutable request-path snapshots and the background refresh lifetime."""

    def __init__(
        self,
        reader: SigningKeyReader,
        source: SigningKeySource,
        clock: Clock,
        *,
        refresh_interval: timedelta = REFRESH_INTERVAL,
    ) -> None:
        """Inject key persistence, private material and time.

        Args:
            reader: The registered-key reader.
            source: The private-key loader.
            clock: The source of snapshot time.
            refresh_interval: Delay between background refreshes.
        """
        self._reader = reader
        self._source = source
        self._clock = clock
        self._refresh_interval = refresh_interval
        self._ring = KeyRing((), {}, clock.now())
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    @property
    def ring(self) -> KeyRing:
        """Return the current immutable snapshot without I/O.

        Returns:
            The last successfully refreshed ring.
        """
        return self._ring

    async def refresh(self) -> KeyRing:
        """Publish a fresh snapshot, reusing keys by their registered identity.

        Returns:
            The new ring, with unloadable pending keys omitted from private material.
        """
        return await self._refresh(strict=False)

    def _private_key(self, record: SigningKeyRecord) -> PrivateSigningKey:
        """Resolve and verify private material against the registered public identity.

        Args:
            record: The registration to load or reuse.

        Returns:
            A matching private key.

        Raises:
            SigningKeyUnavailable: If loading fails or the public identity differs.
        """
        context = {"kid": record.key.kid, "private_ref": record.private_ref}
        try:
            private = self._ring.private_keys.get(record.key.kid)
            if private is None:
                private = self._source.load(record.private_ref)
            public = PublicSigningKey.from_private(private)
            if public.kid != record.key.kid or public.alg != record.key.alg:
                raise SigningKeyUnavailable(context={"reason": "key_mismatch"})
        except SigningKeyUnavailable as exc:
            raise SigningKeyUnavailable(context={**exc.context, **context}) from exc
        return private

    async def _refresh(self, *, strict: bool) -> KeyRing:
        """Serialize snapshot construction and publish only a complete successful read.

        Args:
            strict: Whether every signing key must load, including pending keys.

        Returns:
            The newly published snapshot.

        Raises:
            SigningKeyUnavailable: If a required private key or startup signer is unavailable.
        """
        async with self._lock:
            now = self._clock.now()
            records = await self._reader.unexpired(now - RETENTION)
            private_keys = {}
            for record in records:
                state = record.state(now)
                if state not in {KeyState.PENDING, KeyState.ACTIVE}:
                    continue
                try:
                    private_keys[record.key.kid] = self._private_key(record)
                except SigningKeyUnavailable:
                    if strict or state == KeyState.ACTIVE:
                        raise
                    logging.getLogger(__name__).warning(
                        "Pending signing key unavailable: kid=%s private_ref=%s",
                        record.key.kid,
                        record.private_ref,
                    )
            ring = KeyRing(records, private_keys, now)
            if strict:
                ring.signer(now)
            self._ring = ring
            return ring

    async def __aenter__(self) -> Self:
        """Require all signing keys at startup, then start periodic refreshes.

        Returns:
            This running key-ring owner.
        """
        await self._refresh(strict=True)
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Cancel and await the refresh loop before releasing the owner.

        Args:
            *exc_info: The enclosing context's exception details.
        """
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        """Keep the last snapshot on failures and retry at the refresh interval."""
        while True:
            await asyncio.sleep(self._refresh_interval.total_seconds())
            try:
                await self.refresh()
            except Exception:
                logging.getLogger(__name__).exception("Signing key refresh failed")
