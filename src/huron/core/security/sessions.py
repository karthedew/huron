"""Server-side browser sessions.

The cookie value is ``hs_{session_id}_{secret}``; the database keeps only the
secret's SHA-256, so a leaked sessions table cannot mint cookies. Expiry is
double-bounded: ``idle_expires_at`` slides forward on activity,
``absolute_expires_at`` is fixed at login. Revocation is a row update and
takes effect on the next request.

A session idles out :data:`IDLE_TTL` after its last request and ends
unconditionally :data:`ABSOLUTE_TTL` after login, whichever comes first.
The idle deadline is persisted at most once per :data:`TOUCH_INTERVAL`
and is never extended past the absolute one. Like API keys, resolution is
framework-free: :class:`SessionResolver` depends on :class:`SessionStore`,
and the service adds the cookie handling and CSRF check around it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from .authentication_errors import AuthError
from .principal import Principal

if TYPE_CHECKING:
    from huron.core.foundation.clock import Clock


class SessionExpired(AuthError):
    """A session whose secret matched but whose idle or absolute deadline has passed.

    The ``SESSION_EXPIRED`` condition. The two deadlines are not told
    apart: either way the browser must log in again. A session that is
    both revoked and expired reports revocation instead.
    """

    code = "SESSION_EXPIRED"


class SessionRevoked(AuthError):
    """A session whose secret matched but which has been revoked.

    The ``SESSION_REVOKED`` condition: ``revoked_at`` is set, by logout,
    by a password reset, or by the account being disabled. It is checked
    before expiry, so it wins when both apply.
    """

    code = "SESSION_REVOKED"


IDLE_TTL = timedelta(hours=12)
ABSOLUTE_TTL = timedelta(days=7)
#: last_seen/idle sliding is persisted at most this often, so a busy UI does
#: not turn every GET into a session-table write.
TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One browser session as the store persists it.

    ``secret_sha256`` is the only trace of the cookie's secret, so a
    record can verify a presented cookie but never reproduce one.
    ``csrf_token`` is the value a cookie-authenticated state change must
    echo in ``X-Huron-CSRF``. The principal fields are the login-time
    snapshot described at their declaration; the timestamps carry the two
    expiry bounds plus ``last_seen_at``, which throttles how often the
    sliding bound is written. Records are immutable: touching or revoking
    a session stores a changed copy.
    """

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
    """Persistence for sessions: lookup, creation, sliding-expiry touches, revocation.

    ``get`` must return revoked and expired sessions as well as live ones:
    the resolver is what tells those states apart, and it can only report
    ``SESSION_REVOKED`` or ``SESSION_EXPIRED`` rather than a bare invalid
    credential if the store does not hide them. Every write is visible to
    the next request that presents the cookie; the resolver caches
    nothing.
    """

    async def get(self, session_id: UUID) -> SessionRecord | None:
        """Return the session with this id, whether live, expired or revoked.

        Args:
            session_id: The id parsed from the cookie value.

        Returns:
            The stored record, or None if no session has this id.
        """
        ...

    async def add(self, record: SessionRecord) -> None:
        """Persist a newly created session.

        Args:
            record: The record half of :func:`create_session`'s result.
        """
        ...

    async def touch(
        self, session_id: UUID, last_seen_at: datetime, idle_expires_at: datetime
    ) -> None:
        """Record activity on a session by moving its idle deadline forward.

        Args:
            session_id: The session that just authenticated a request.
            last_seen_at: The instant of that request.
            idle_expires_at: The new idle deadline; the resolver has
                already capped it at the absolute deadline.
        """
        ...

    async def revoke(self, session_id: UUID, revoked_at: datetime) -> None:
        """Mark one session revoked; a no-op for an id that does not exist.

        Args:
            session_id: The session to end.
            revoked_at: The instant to record on it.
        """
        ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke every live session a subject holds.

        This is what a password reset and an account disable call, so no
        browser stays signed in on a credential that no longer stands.

        Args:
            subject: The subject whose sessions end.
            revoked_at: The instant recorded on each newly revoked session.

        Returns:
            How many sessions were live and are now revoked.
        """
        ...


def create_session(
    subject: str,
    *,
    groups: frozenset[str] = frozenset(),
    authentication_method: str,
    now: datetime | None = None,
) -> tuple[SessionRecord, str]:
    """Start a session, returning the record to persist and the one-time cookie value.

    The cookie value is ``hs_{session_id}_{secret}`` and is shown once:
    the record keeps the secret's SHA-256 and a fresh CSRF token, never
    the secret. Both deadlines are set from ``now``, the idle one
    :data:`IDLE_TTL` ahead and the absolute one :data:`ABSOLUTE_TTL`
    ahead. Nothing is stored here; the caller adds the record to a store.

    Args:
        subject: The principal the session is for, as the principal store
            names it.
        groups: The group snapshot carried for the session's lifetime -
            the identity provider's claim for an OIDC login, empty for a
            password login.
        authentication_method: How the user proved themselves at login,
            ``"oidc"`` or ``"password"``; recorded on the session.
        now: The login instant, for deterministic tests; the current UTC
            time when omitted.

    Returns:
        The record and the cookie value, in that order.
    """
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
    """Parse the session id segment of a cookie value, or None if it is not a UUID.

    Args:
        raw: The middle segment of an ``hs_{session_id}_{secret}`` value.

    Returns:
        The id, or None when ``raw`` does not parse as a UUID; the caller
        turns that into the same error as any other malformed token.
    """
    try:
        return UUID(hex=raw)
    except ValueError:
        return None


def parse_session_token(token: str) -> tuple[UUID, str]:
    """Split an ``hs_{session_id}_{secret}`` cookie value into its id and secret.

    Only the shape is checked; nothing is looked up. The split is on the
    first two underscores, so a secret that itself contains underscores
    (URL-safe base64 can) survives intact.

    Args:
        token: The raw cookie value.

    Returns:
        The session id and the secret, in that order.

    Raises:
        AuthError: If the prefix is not ``hs``, the id is not a UUID, or
            the secret is missing.
    """
    prefix, _, remainder = token.partition("_")
    raw_id, separator, secret = remainder.partition("_")
    session_id = _parse_session_id(raw_id)
    if prefix != "hs" or not separator or session_id is None or not secret:
        raise AuthError("invalid session token format")
    return session_id, secret


class SessionResolver:
    """Turn a session cookie value into a :class:`Principal` and its current record.

    As with API keys, the secret is hashed and compared against a dummy
    digest when the id is unknown, so a probe cannot tell an unknown id
    from a wrong secret. A valid session's idle deadline slides forward,
    but the slide is persisted only once :data:`TOUCH_INTERVAL` has passed
    since ``last_seen_at``: the stored deadline therefore lags real
    activity by up to that interval, which is the price of not writing
    on every request.
    """

    def __init__(self, store: SessionStore, *, clock: Clock | None = None):
        """Bind the resolver to the store sessions live in.

        Args:
            store: The session persistence; ``touch`` is the only write
                the resolver performs through it.
            clock: Time sampled after lookup and secret verification; defaults to UTC wall time.
        """
        self.store = store
        self._clock = clock

    async def resolve(
        self, token: str, *, now: datetime | None = None
    ) -> tuple[Principal, SessionRecord]:
        """Verify a session cookie value and produce the principal behind it.

        Args:
            token: The raw cookie value in the ``hs_{session_id}_{secret}``
                form.
            now: The instant expiry and touch throttling are judged
                against, overriding the clock for deterministic tests. When omitted,
                sample the clock after lookup and secret verification.

        Returns:
            The principal, with ``authentication_method`` ``"session"``
            and kind ``"user"``, and the session record as it stands after
            this request - with ``last_seen_at`` and ``idle_expires_at``
            already advanced when a touch was persisted, so the caller
            sees the same deadlines the store does. The new idle deadline
            is never later than the absolute one.

        Raises:
            AuthError: If the token is malformed, names an unknown
                session, or carries a secret that does not match.
            SessionRevoked: If the session has been revoked.
            SessionExpired: If either the idle or the absolute deadline
                has been reached.
        """
        session_id, secret = parse_session_token(token)
        record = await self.store.get(session_id)
        candidate = hashlib.sha256(secret.encode()).hexdigest()
        expected = record.secret_sha256 if record is not None else "0" * 64
        if record is None or not hmac.compare_digest(candidate, expected):
            raise AuthError("invalid session")
        moment = now or (self._clock.now() if self._clock is not None else datetime.now(UTC))
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
    "SessionExpired",
    "SessionRecord",
    "SessionResolver",
    "SessionRevoked",
    "SessionStore",
    "create_session",
    "parse_session_token",
]
