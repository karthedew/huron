"""API-key issuance, storage, and resolution to a Principal."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from .errors import ApiKeyExpired, ApiKeyRevoked, AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
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
    async def get(self, key_id: str) -> ApiKeyRecord | None: ...


class MemoryApiKeyStore:
    def __init__(self, records: Mapping[str, ApiKeyRecord] | None = None):
        self.records = dict(records or {})
        #: key_ids passed to touch_last_used, in call order - lets tests assert
        #: the touch actually happened without needing a last_used_at field.
        self.touched: list[str] = []

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        return self.records.get(key_id)

    async def add(self, record: ApiKeyRecord) -> None:
        self.records[record.key_id] = record

    async def touch_last_used(self, key_id: str) -> None:
        self.touched.append(key_id)


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
    def __init__(self, store: ApiKeyStore):
        self.store = store

    async def resolve(self, credential: str, *, now: datetime | None = None) -> Principal:
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
    token = credential.removeprefix("Bearer ").strip()
    prefix, separator, remainder = token.partition("_")
    key_id, second_separator, secret = remainder.partition("_")
    if prefix != "hk" or not separator or not second_separator or not key_id or not secret:
        raise AuthError("invalid API key format")
    return key_id, secret


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


__all__ = [
    "ApiKeyRecord",
    "ApiKeyResolver",
    "ApiKeyStore",
    "MemoryApiKeyStore",
    "create_api_key",
    "parse_api_key",
]
