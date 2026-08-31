"""Server-side browser sessions.

The cookie value is ``hs_{session_id}_{secret}``; the database keeps only the
secret's SHA-256, so a leaked sessions table cannot mint cookies. Expiry is
double-bounded: ``idle_expires_at`` slides forward on activity,
``absolute_expires_at`` is fixed at login. Revocation is a row update and
takes effect on the next request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from .errors import AuthError
from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Mapping


class SessionExpired(AuthError):
    code = "SESSION_EXPIRED"


class SessionRevoked(AuthError):
    code = "SESSION_REVOKED"


IDLE_TTL = timedelta(hours=12)
ABSOLUTE_TTL = timedelta(days=7)
#: last_seen/idle sliding is persisted at most this often, so a busy UI does
#: not turn every GET into a session-table write.
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: UUID
    secret_sha256: str
    csrf_token: str
    #: Denormalized principal snapshot taken at login. Groups refresh at next
    #: login, not mid-session - same tradeoff as an OIDC token's lifetime.
    subject: str
    groups: frozenset[str]
    authentication_method: str  # "oidc" | "password"
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None


class SessionStore(Protocol):
    async def get(self, session_id: UUID) -> SessionRecord | None: ...

    async def add(self, record: SessionRecord) -> None: ...

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None: ...

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None: ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int: ...


class MemorySessionStore:
    def __init__(self, records: Mapping[UUID, SessionRecord] | None = None):
        self.records = dict(records or {})
        #: session ids passed to touch, in call order - lets tests assert the
        #: touch throttling without needing a last_seen_at field on the store.
        self.touched: list[UUID] = []

    async def get(self, session_id: UUID) -> SessionRecord | None:
        return self.records.get(session_id)

    async def add(self, record: SessionRecord) -> None:
        self.records[record.id] = record

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None:
        self.touched.append(session_id)
        record = self.records.get(session_id)
        if record is not None:
            self.records[session_id] = replace(
                record, last_seen_at=last_seen_at, idle_expires_at=idle_expires_at
            )

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        record = self.records.get(session_id)
        if record is not None:
            self.records[session_id] = replace(record, revoked_at=revoked_at)

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        count = 0
        for session_id, record in self.records.items():
            if record.subject == subject and record.revoked_at is None:
                self.records[session_id] = replace(record, revoked_at=revoked_at)
                count += 1
        return count


def create_session(
    subject: str,
    *,
    groups: frozenset[str] = frozenset(),
    authentication_method: str,
    now: datetime | None = None,
) -> tuple[SessionRecord, str]:
    """Return the record to persist and the ``hs_…`` cookie value (shown once)."""
    created_at = now or datetime.now(UTC)
    session_id = uuid4()
    secret = secrets.token_urlsafe(32)
    record = SessionRecord(
        id=session_id,
        secret_sha256=hashlib.sha256(secret.encode()).hexdigest(),
        csrf_token=secrets.token_urlsafe(32),
        subject=subject,
        groups=groups,
        authentication_method=authentication_method,
        created_at=created_at,
        last_seen_at=created_at,
        idle_expires_at=created_at + IDLE_TTL,
        absolute_expires_at=created_at + ABSOLUTE_TTL,
    )
    return record, f"hs_{session_id.hex}_{secret}"


def _parse_session_id(raw: str) -> UUID | None:
    try:
        return UUID(hex=raw)
    except ValueError:
        return None


def parse_session_token(token: str) -> tuple[UUID, str]:
    prefix, _, remainder = token.partition("_")
    raw_id, separator, secret = remainder.partition("_")
    session_id = _parse_session_id(raw_id)
    if prefix != "hs" or not separator or session_id is None or not secret:
        raise AuthError("invalid session token format")
    return session_id, secret


class SessionResolver:
    def __init__(self, store: SessionStore):
        self.store = store

    async def resolve(
        self, token: str, *, now: datetime | None = None
    ) -> tuple[Principal, SessionRecord]:
        session_id, secret = parse_session_token(token)
        record = await self.store.get(session_id)
        candidate = hashlib.sha256(secret.encode()).hexdigest()
        expected = record.secret_sha256 if record is not None else "0" * 64
        if record is None or not hmac.compare_digest(candidate, expected):
            raise AuthError("invalid session")
        moment = now or datetime.now(UTC)
        if record.revoked_at is not None:
            raise SessionRevoked("session has been revoked")
        if moment >= record.idle_expires_at or moment >= record.absolute_expires_at:
            raise SessionExpired("session has expired")
        if moment - record.last_seen_at >= TOUCH_INTERVAL:
            new_idle = min(moment + IDLE_TTL, record.absolute_expires_at)
            await self.store.touch(record.id, moment, new_idle)
            record = replace(record, last_seen_at=moment, idle_expires_at=new_idle)
        principal = Principal(
            subject=record.subject,
            groups=record.groups,
            authentication_method="session",
            kind="user",
        )
        return principal, record


__all__ = [
    "ABSOLUTE_TTL",
    "IDLE_TTL",
    "TOUCH_INTERVAL",
    "MemorySessionStore",
    "SessionExpired",
    "SessionRecord",
    "SessionResolver",
    "SessionRevoked",
    "SessionStore",
    "create_session",
    "parse_session_token",
]
