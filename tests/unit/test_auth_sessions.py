"""Server-side session tokens, proved against MemorySessionStore and SessionResolver.

Covers format parsing, double-bounded expiry, touch throttling, and
revocation.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from huron.pkg.auth.errors import AuthError
from huron.pkg.auth.sessions import (
    ABSOLUTE_TTL,
    IDLE_TTL,
    TOUCH_INTERVAL,
    MemorySessionStore,
    SessionExpired,
    SessionResolver,
    SessionRevoked,
    create_session,
    parse_session_token,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_create_session_token_matches_the_hs_prefixed_golden_format() -> None:
    """``create_session``'s token starts with ``hs_``, embeds the session id, then a secret."""
    record, token = create_session("alice", authentication_method="password", now=T0)
    # The secret half is base64url and may itself contain underscores, so
    # only the first two underscores are structural.
    prefix, id_part, secret = token.split("_", 2)
    assert prefix == "hs"
    assert id_part == record.id.hex
    assert secret


def test_parse_session_token_recovers_the_id_and_matches_the_stored_hash() -> None:
    """``parse_session_token`` recovers the id and a secret whose hash matches the record."""
    record, token = create_session("alice", authentication_method="password", now=T0)
    session_id, secret = parse_session_token(token)
    assert session_id == record.id
    assert hashlib.sha256(secret.encode()).hexdigest() == record.secret_sha256


@pytest.mark.parametrize(
    "token",
    [
        "",
        "hs_",
        "hs_notauuid_secret",
        "wrongprefix_00000000000000000000000000000000_secret",
        "hs_00000000000000000000000000000000_",
        "hs_00000000000000000000000000000000",
        "00000000000000000000000000000000_secret",
    ],
)
def test_parse_session_token_rejects_malformed_tokens(token: str) -> None:
    """A malformed session token is rejected however its shape is broken."""
    with pytest.raises(AuthError):
        parse_session_token(token)


async def test_resolver_returns_a_session_principal_for_a_fresh_token() -> None:
    """A fresh, valid session token resolves to a session principal and its record."""
    store = MemorySessionStore()
    record, token = create_session(
        "alice", groups=frozenset({"physics"}), authentication_method="password", now=T0
    )
    await store.add(record)
    resolver = SessionResolver(store)

    principal, resolved = await resolver.resolve(token, now=T0)

    assert principal.subject == "alice"
    assert principal.groups == frozenset({"physics"})
    assert principal.authentication_method == "session"
    assert principal.kind == "user"
    assert resolved.id == record.id


async def test_resolver_rejects_a_wrong_secret_with_a_valid_session_id() -> None:
    """A token with the right session id but a wrong secret is rejected."""
    store = MemorySessionStore()
    record, _ = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)
    tampered = f"hs_{record.id.hex}_wrong-secret-entirely"

    with pytest.raises(AuthError) as excinfo:
        await resolver.resolve(tampered, now=T0)
    assert excinfo.type is AuthError


async def test_resolver_rejects_an_unknown_session_id() -> None:
    """A token naming a session id the store has never seen is rejected."""
    store = MemorySessionStore()
    resolver = SessionResolver(store)
    _, token = create_session("alice", authentication_method="password", now=T0)

    with pytest.raises(AuthError) as excinfo:
        await resolver.resolve(token, now=T0)
    assert excinfo.type is AuthError


async def test_idle_expiry_slides_forward_on_use() -> None:
    """Resolving a session past the touch interval slides its idle deadline forward."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)
    original_idle = record.idle_expires_at

    later = T0 + TOUCH_INTERVAL + timedelta(seconds=1)
    _, resolved = await resolver.resolve(token, now=later)

    assert resolved.idle_expires_at > original_idle
    assert resolved.last_seen_at == later


async def test_absolute_expiry_never_slides() -> None:
    """A session's absolute expiry never moves, even when the idle deadline slides."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)
    original_absolute = record.absolute_expires_at

    later = T0 + TOUCH_INTERVAL + timedelta(seconds=1)
    _, resolved = await resolver.resolve(token, now=later)

    assert resolved.absolute_expires_at == original_absolute


async def test_idle_expiry_is_capped_at_the_absolute_deadline() -> None:
    """A touch that would push idle_expires_at past the absolute deadline is clamped there.

    Late in a session's life a touch would push idle_expires_at past the
    absolute deadline; it must be clamped there instead, simulated here by
    starting from a record already near that deadline.
    """
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    near_absolute_deadline = record.absolute_expires_at - timedelta(hours=1)
    record = replace(record, idle_expires_at=near_absolute_deadline)
    await store.add(record)
    resolver = SessionResolver(store)

    moment = near_absolute_deadline - timedelta(minutes=1)
    _, resolved = await resolver.resolve(token, now=moment)

    assert resolved.idle_expires_at == record.absolute_expires_at


async def test_session_expires_once_the_idle_deadline_passes() -> None:
    """A session is expired the instant ``now`` reaches its idle deadline."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)

    with pytest.raises(SessionExpired):
        await resolver.resolve(token, now=record.idle_expires_at)


async def test_session_expires_once_the_absolute_deadline_passes_even_if_idle() -> None:
    """A session is expired once ``now`` reaches its absolute deadline."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)

    with pytest.raises(SessionExpired):
        await resolver.resolve(token, now=record.absolute_expires_at)


async def test_touch_is_throttled_to_at_most_once_per_touch_interval() -> None:
    """A touch is recorded at most once per TOUCH_INTERVAL, not on every request."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    resolver = SessionResolver(store)

    just_under_the_interval = T0 + TOUCH_INTERVAL - timedelta(seconds=1)
    await resolver.resolve(token, now=just_under_the_interval)
    assert store.touched == []

    past_the_interval = T0 + TOUCH_INTERVAL + timedelta(seconds=1)
    await resolver.resolve(token, now=past_the_interval)
    assert store.touched == [record.id]

    # A second request immediately after a touch stays under the interval
    # again and must not trigger a second write.
    await resolver.resolve(token, now=past_the_interval + timedelta(seconds=1))
    assert store.touched == [record.id]


async def test_revoked_session_is_rejected_even_before_expiry() -> None:
    """A revoked session is refused before its expiry is even considered."""
    store = MemorySessionStore()
    record, token = create_session("alice", authentication_method="password", now=T0)
    await store.add(record)
    await store.revoke(record.id, T0 + timedelta(minutes=1))
    resolver = SessionResolver(store)

    with pytest.raises(SessionRevoked):
        await resolver.resolve(token, now=T0 + timedelta(minutes=2))


async def test_revoke_all_for_only_touches_the_subjects_active_sessions() -> None:
    """``revoke_all_for`` revokes only a subject's still-live sessions, leaving others alone."""
    store = MemorySessionStore()
    alice_record, _ = create_session("alice", authentication_method="password", now=T0)
    alice_second_record, _ = create_session("alice", authentication_method="password", now=T0)
    bob_record, _ = create_session("bob", authentication_method="password", now=T0)
    await store.add(alice_record)
    await store.add(alice_second_record)
    await store.add(bob_record)
    await store.revoke(alice_second_record.id, T0)

    revoked_count = await store.revoke_all_for("alice", T0 + timedelta(minutes=1))

    alice_after = await store.get(alice_record.id)
    bob_after = await store.get(bob_record.id)
    assert revoked_count == 1
    assert alice_after is not None
    assert alice_after.revoked_at == T0 + timedelta(minutes=1)
    assert bob_after is not None
    assert bob_after.revoked_at is None


def test_idle_and_absolute_ttls_are_the_documented_lengths() -> None:
    """``IDLE_TTL`` is 12 hours and ``ABSOLUTE_TTL`` is 7 days, as documented."""
    assert timedelta(hours=12) == IDLE_TTL
    assert timedelta(days=7) == ABSOLUTE_TTL
