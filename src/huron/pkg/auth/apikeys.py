"""API-key issuance, storage, and resolution to a Principal.

A key is shown to its owner exactly once, as ``hk_{key_id}_{secret}``; the
store keeps ``key_id`` and the secret's SHA-256, never the secret itself,
so a leaked table cannot be replayed as credentials. ``key_id`` is a random
opaque handle that finds the record, and the secret is what proves
possession. Resolution only reads: :class:`ApiKeyResolver` depends on the
single-method :class:`ApiKeyStore`, while the write path (``add``,
``touch_last_used``, ``revoke_all_for``) is the service repository's own
extension, which :class:`MemoryApiKeyStore` implements here.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from .errors import ApiKeyExpired, ApiKeyRevoked, AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    """One issued API key as the store persists it - everything except the secret.

    ``secret_sha256`` is the only trace of the secret, so a record can
    verify a presented key but never reproduce one. ``subject`` and
    ``owner_kind`` become the resolved :class:`Principal`'s identity and
    kind, and ``scopes`` and ``project_id`` are the restrictions the key
    was minted with. A key stops resolving once the instant in
    ``expires_at`` is reached or ``revoked_at`` is set; the resolver, not
    the store, enforces both.
    """

    key_id: str
    subject: str
    #: The caller-supplied label for this key, as shown back in API responses
    #: and persisted to storage - distinct from ``key_id``, which is an
    #: opaque handle, not a name.
    name: str
    secret_sha256: str
    scopes: frozenset[str]
    project_id: str | None
    expires_at: datetime
    revoked_at: datetime | None = None
    owner_kind: str = "user"


class ApiKeyStore(Protocol):
    """The read-only lookup :class:`ApiKeyResolver` needs from persistence.

    Deliberately a single ``get``: resolving a key never writes, so a store
    that can only read is enough to authenticate against. The service's
    repository widens this contract with the write path.
    """

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        """Return the record for a key id, in whatever state it is in.

        An implementation must return expired and revoked records too: the
        resolver is what tells those states apart from an unknown key, and
        it can only do so if the store does not hide them.

        Args:
            key_id: The opaque handle from an ``hk_{key_id}_{secret}``
                credential.

        Returns:
            The stored record, or None if no key has this id.
        """
        ...


class MemoryApiKeyStore:
    """An in-memory :class:`ApiKeyStore` that also carries the repository's write path.

    The repository's default when no Postgres store is injected. Records
    live in a dict keyed by ``key_id`` and nothing outlives the process;
    the store satisfies the service's ``ApiKeyWriter`` structurally, so
    the same route and resolver code runs against it and against the
    ``api_keys`` table.
    """

    def __init__(self, records: Mapping[str, ApiKeyRecord] | None = None):
        """Seed the store.

        Args:
            records: Initial records keyed by ``key_id``. They are copied
                into the store's own dict, so later changes to the mapping
                are not seen. Empty when omitted.
        """
        self.records = dict(records or {})
        #: key_ids passed to touch_last_used, in call order - lets tests assert
        #: the touch actually happened without needing a last_used_at field.
        self.touched: list[str] = []

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        """Return the record for a key id, expired and revoked ones included.

        Args:
            key_id: The opaque handle from the credential.

        Returns:
            The stored record, or None if no key has this id.
        """
        return self.records.get(key_id)

    async def add(self, record: ApiKeyRecord) -> None:
        """Store a newly minted record, replacing any that shares its ``key_id``.

        Args:
            record: The record half of :func:`create_api_key`'s result.
        """
        self.records[record.key_id] = record

    async def touch_last_used(self, key_id: str) -> None:
        """Note that a key authenticated a request by appending its id to ``touched``.

        The memory store keeps no ``last_used_at``; the ordered list is
        what tests inspect to prove the bookkeeping call was made.

        Args:
            key_id: The key that was just used; it need not exist in the
                store.
        """
        self.touched.append(key_id)

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke every live key a subject owns.

        A key already revoked keeps its original ``revoked_at`` and is not
        counted again, so the count is exactly the number of keys this
        call took out of service.

        Args:
            subject: The owner whose keys are revoked, whatever their
                ``owner_kind``.
            revoked_at: The instant recorded on each newly revoked key.

        Returns:
            How many keys this call revoked.
        """
        count = 0
        for key_id, record in self.records.items():
            if record.subject == subject and record.revoked_at is None:
                self.records[key_id] = replace(record, revoked_at=revoked_at)
                count += 1
        return count


def create_api_key(
    subject: str,
    *,
    name: str,
    scopes: frozenset[str] = frozenset({"read"}),
    project_id: str | None = None,
    now: datetime | None = None,
    ttl: timedelta = timedelta(days=90),
    owner_kind: str = "user",
) -> tuple[ApiKeyRecord, str]:
    """Mint a key, returning the record to persist and the one-time credential.

    The credential is the only copy of the secret that will ever exist:
    the record carries its SHA-256 and nothing else, so the caller must
    show the credential to the owner in the same response and can never
    recover it afterwards. Nothing is stored here; the caller adds the
    record to a store.

    Args:
        subject: The principal that owns the key and that the key resolves
            to.
        name: The owner's label for the key, echoed in API responses and
            persisted alongside it.
        scopes: The scopes the resolved principal carries; read-only when
            omitted.
        project_id: A project to restrict the key to, or None for no
            restriction.
        now: The creation instant, for deterministic tests; the current
            UTC time when omitted.
        ttl: How long the key stays valid from ``now``. Must be positive
            and at most 400 days, so no key can be minted that in practice
            never expires.
        owner_kind: ``"user"`` or ``"service_account"``, copied into the
            resolved principal's ``kind``.

    Returns:
        The record, with ``expires_at`` set to ``now + ttl``, and the
        ``hk_{key_id}_{secret}`` credential.

    Raises:
        ValueError: If ``ttl`` is not positive or exceeds 400 days.
    """
    if ttl <= timedelta(0) or ttl > timedelta(days=400):
        raise ValueError("API key TTL must be between 1 second and 400 days")
    created_at = now or datetime.now(UTC)
    key_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    record = ApiKeyRecord(
        key_id=key_id,
        subject=subject,
        name=name,
        secret_sha256=_digest(secret),
        scopes=scopes,
        project_id=project_id,
        expires_at=created_at + ttl,
        owner_kind=owner_kind,
    )
    return record, f"hk_{key_id}_{secret}"


class ApiKeyResolver:
    """Turn an ``hk_`` bearer credential into a :class:`Principal`.

    Resolution has the same shape whether or not the key id exists: the
    presented secret is hashed and compared against a dummy digest on a
    miss, so a probe cannot tell an unknown id from a wrong secret by
    timing or by error code. Revocation and expiry are reported only for
    a key whose secret matched.
    """

    def __init__(self, store: ApiKeyStore):
        """Bind the resolver to the store it looks keys up in.

        Args:
            store: Any read-only key lookup; nothing is written through it.
        """
        self.store = store

    async def resolve(self, credential: str, *, now: datetime | None = None) -> Principal:
        """Verify an API-key credential and produce the principal it stands for.

        Args:
            credential: The bearer value, with or without its ``Bearer``
                prefix, in the ``hk_{key_id}_{secret}`` form.
            now: The instant expiry is judged against, for deterministic
                tests; the current UTC time when omitted.

        Returns:
            A principal carrying the record's subject, scopes, project
            restriction and owner kind, with ``authentication_method``
            ``"api-key"``.

        Raises:
            AuthError: If the credential is malformed, names an unknown
                key id, or carries a secret that does not match.
            ApiKeyRevoked: If the key has been revoked.
            ApiKeyExpired: If ``expires_at`` has been reached; a key that
                is both revoked and expired reports revocation.
        """
        key_id, secret = parse_api_key(credential)
        record = await self.store.get(key_id)
        # Hash even on a miss to avoid making the lookup outcome more obvious.
        candidate = _digest(secret)
        expected = record.secret_sha256 if record is not None else "0" * 64
        matches = hmac.compare_digest(candidate, expected)
        if record is None or not matches:
            raise AuthError("invalid API key")
        if record.revoked_at is not None:
            raise ApiKeyRevoked("API key has been revoked")
        if record.expires_at <= (now or datetime.now(UTC)):
            raise ApiKeyExpired("API key has expired")
        return Principal(
            subject=record.subject,
            scopes=record.scopes,
            project_id=record.project_id,
            authentication_method="api-key",
            kind=record.owner_kind,
        )


def parse_api_key(credential: str) -> tuple[str, str]:
    """Split an ``hk_{key_id}_{secret}`` credential into its key id and secret.

    Only the shape is checked; nothing is looked up. A leading ``Bearer``
    prefix and surrounding whitespace are tolerated so a raw
    ``Authorization`` header value can be passed straight in. The split is
    on the first two underscores only, so a secret that itself contains
    underscores (URL-safe base64 can) survives intact.

    Args:
        credential: The bearer value as the caller presented it.

    Returns:
        The key id and the secret, in that order.

    Raises:
        AuthError: If the prefix is not ``hk`` or either part is missing.
    """
    token = credential.removeprefix("Bearer ").strip()
    prefix, separator, remainder = token.partition("_")
    key_id, second_separator, secret = remainder.partition("_")
    if prefix != "hk" or not separator or not second_separator or not key_id or not secret:
        raise AuthError("invalid API key format")
    return key_id, secret


def _digest(secret: str) -> str:
    """Return the hex SHA-256 of a secret, the form the store keeps and compares.

    Args:
        secret: The secret half of a credential.

    Returns:
        The 64-character lower-case hex digest.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


__all__ = [
    "ApiKeyRecord",
    "ApiKeyResolver",
    "ApiKeyStore",
    "MemoryApiKeyStore",
    "create_api_key",
    "parse_api_key",
]
