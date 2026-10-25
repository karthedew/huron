"""Signing keys preserve immutable identity, publication windows and rotation continuity."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from huron.core.security.broker import (
    JWKS_MAX_AGE,
    MAX_RING_AGE,
    MIN_PUBLICATION_LEAD,
    REFRESH_INTERVAL,
    RETENTION,
    TOKEN_TTL_MAX,
    VERIFY_LEEWAY,
    KeyRing,
    KeyState,
    PrivateSigningKey,
    PublicSigningKey,
    SigningKeyRecord,
    initial_record,
    jwk_thumbprint,
    plan_rotation,
)
from huron.core.security.errors import RotationRefused, SigningKeyUnavailable

pytestmark = pytest.mark.unit

AT = datetime(2026, 1, 1, tzinfo=UTC)
TICK = timedelta(microseconds=1)
PRIVATE = ec.derive_private_key(1, ec.SECP256R1())
SUCCESSOR_PRIVATE = ec.derive_private_key(2, ec.SECP256R1())
PUBLIC = PublicSigningKey.from_private(PRIVATE)
SUCCESSOR = PublicSigningKey.from_private(SUCCESSOR_PRIVATE)


def test_thumbprint_matches_rfc_example_and_ignores_optional_members() -> None:
    """The published RFC 7638 RSA vector pins canonicalization and base64url encoding."""
    members = {
        "kty": "RSA",
        "n": (
            "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAt"
            "VT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn6"
            "4tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FD"
            "W2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n9"
            "1CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINH"
            "aQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
        ),
        "e": "AQAB",
        "alg": "RS256",
        "kid": "2011-04-29",
    }
    assert jwk_thumbprint(members) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"
    assert jwk_thumbprint(dict(reversed(list(members.items())))) == jwk_thumbprint(members)


@pytest.mark.parametrize("algorithm", ["ES256", "RS256"])
def test_private_key_loads_have_equal_public_values_and_usable_jwks(algorithm: str) -> None:
    """Both allowed key types round-trip by value and render a matching verification key."""
    private = PRIVATE if algorithm == "ES256" else rsa.generate_private_key(65537, 2048)
    encoded = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    first = PublicSigningKey.from_private(serialization.load_pem_private_key(encoded, None))
    second = PublicSigningKey.from_private(serialization.load_pem_private_key(encoded, None))
    assert first == second
    assert first.alg == algorithm
    assert first.kid == jwk_thumbprint(first.members)
    assert len(first.kid) == 43
    assert set(first.members) == (
        {"kty", "crv", "x", "y"} if algorithm == "ES256" else {"kty", "e", "n"}
    )
    assert first.as_jwk() == {**first.members, "kid": first.kid, "alg": algorithm, "use": "sig"}
    token = jwt.encode({"sub": "scientist"}, private, algorithm=algorithm)
    assert jwt.decode(token, jwt.PyJWK(first.as_jwk()), algorithms=[algorithm]) == {
        "sub": "scientist"
    }
    assert encoded.decode() not in repr(first)


@pytest.mark.parametrize("kind", ["p384", "rsa1024", "ed25519"])
def test_unsupported_private_keys_are_refused(kind: str) -> None:
    """Other curves, short RSA keys and other key families cannot become signing keys."""
    key = {
        "p384": lambda: ec.derive_private_key(1, ec.SECP384R1()),
        "rsa1024": lambda: rsa.generate_private_key(65537, 1024),
        "ed25519": ed25519.Ed25519PrivateKey.generate,
    }[kind]()
    with pytest.raises(ValueError, match="Signing requires"):
        PublicSigningKey.from_private(key)


def test_thumbprint_refuses_an_unsupported_key_type() -> None:
    """The signing thumbprint routine refuses keys outside the supported public families."""
    with pytest.raises(ValueError, match="Unsupported signing key type"):
        jwk_thumbprint({"kty": "oct", "k": "not-a-public-key"})


def test_public_members_and_rendered_jwk_cannot_mutate_the_value() -> None:
    """Input mappings and JWK outputs never expose mutable state of a public key."""
    members = dict(PUBLIC.members)
    key = PublicSigningKey(PUBLIC.kid, PUBLIC.alg, members)
    members["x"] = "changed"
    assert key == PUBLIC
    rendered = key.as_jwk()
    rendered["x"] = "changed"
    assert key == PUBLIC
    with pytest.raises(TypeError):
        key.members["x"] = "changed"
    with pytest.raises(FrozenInstanceError):
        key.kid = "changed"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (-TICK, KeyState.PENDING),
        (timedelta(), KeyState.ACTIVE),
        (timedelta(hours=1) - TICK, KeyState.ACTIVE),
        (timedelta(hours=1), KeyState.RETIRING),
        (timedelta(hours=1) + RETENTION - TICK, KeyState.RETIRING),
        (timedelta(hours=1) + RETENTION, KeyState.RETIRED),
    ],
)
def test_state_and_publication_share_exact_lifecycle_boundaries(
    offset: timedelta, expected: KeyState
) -> None:
    """Pending through retiring keys verify and publish; retention ends at its exact boundary."""
    record = SigningKeyRecord(PUBLIC, "first.pem", AT, AT + timedelta(hours=1))
    ring = KeyRing((record,), {}, AT)
    at = AT + offset
    assert record.state(at) == expected
    published = expected != KeyState.RETIRED
    assert ring.verification_key(PUBLIC.kid, at) == (PUBLIC if published else None)
    assert ring.jwks(at) == {"keys": [PUBLIC.as_jwk()] if published else []}
    assert ring.algorithms(at) == (("ES256",) if published else ())
    assert ring.verification_key("absent", at) is None


def test_bootstrap_is_immediately_active_and_has_no_retirement() -> None:
    """The first key has an open-ended signing interval starting exactly at bootstrap."""
    record = initial_record(PUBLIC, "first.pem", AT)
    assert record == SigningKeyRecord(PUBLIC, "first.pem", AT, None)
    assert record.state(AT - TICK) == KeyState.PENDING
    assert record.state(AT) == KeyState.ACTIVE
    assert record.state(AT + timedelta(days=365)) == KeyState.ACTIVE
    with pytest.raises(FrozenInstanceError):
        record.retired_at = AT


def test_rotation_keeps_exactly_one_signer_at_the_switch() -> None:
    """A valid minimum-lead rotation retires its predecessor exactly when the successor signs."""
    original = initial_record(PUBLIC, "first.pem", AT)
    before = KeyRing((original,), {PUBLIC.kid: PRIVATE}, AT)
    switch = AT + MIN_PUBLICATION_LEAD
    rotation = plan_rotation(before, SUCCESSOR, "second.pem", switch, AT)
    assert rotation.retire_kid == PUBLIC.kid
    assert rotation.retired_at == rotation.insert.active_from == switch
    assert rotation.insert == initial_record(SUCCESSOR, "second.pem", switch)
    assert before.records == (original,)
    records = (replace(original, retired_at=rotation.retired_at), rotation.insert)
    ring = KeyRing(records, {PUBLIC.kid: PRIVATE, SUCCESSOR.kid: SUCCESSOR_PRIVATE}, switch)
    assert ring.signer(switch - TICK) == (records[0], PRIVATE)
    assert ring.signer(switch) == (records[1], SUCCESSOR_PRIVATE)
    assert ring.signer(switch + TICK) == (records[1], SUCCESSOR_PRIVATE)
    assert ring.jwks(switch)["keys"] == [PUBLIC.as_jwk(), SUCCESSOR.as_jwk()]
    with pytest.raises(FrozenInstanceError):
        rotation.retired_at = AT


@pytest.mark.parametrize(
    ("records", "private_keys", "at", "reason"),
    [
        ((), {}, AT + MAX_RING_AGE + TICK, "stale"),
        ((), {}, AT, "no_active_key"),
        ((initial_record(PUBLIC, "first.pem", AT + TICK),), {}, AT, "no_active_key"),
        ((initial_record(PUBLIC, "first.pem", AT),), {}, AT, "not_loaded"),
    ],
)
def test_unavailable_signer_reports_the_specific_reason(
    records: tuple[SigningKeyRecord, ...],
    private_keys: dict[str, PrivateSigningKey],
    at: datetime,
    reason: str,
) -> None:
    """Staleness takes precedence; otherwise absence and an unloaded active key are distinct."""
    ring = KeyRing(records, private_keys, AT)
    with pytest.raises(SigningKeyUnavailable) as failure:
        ring.signer(at)
    assert failure.value.context["reason"] == reason
    if reason == "not_loaded":
        assert failure.value.context["kid"] == PUBLIC.kid


def test_staleness_boundary_only_blocks_signing() -> None:
    """An exactly five-minute snapshot still signs, while stale rings continue to publish and verify."""
    record = initial_record(PUBLIC, "first.pem", AT)
    ring = KeyRing((record,), {PUBLIC.kid: PRIVATE}, AT)
    assert ring.signer(AT + MAX_RING_AGE) == (record, PRIVATE)
    with pytest.raises(SigningKeyUnavailable) as failure:
        ring.signer(AT + MAX_RING_AGE + TICK)
    assert failure.value.context == {"reason": "stale"}
    later = AT + timedelta(days=1)
    assert ring.verification_key(PUBLIC.kid, later) == PUBLIC
    assert ring.jwks(later) == {"keys": [PUBLIC.as_jwk()]}
    assert ring.algorithms(later) == ("ES256",)


@pytest.mark.parametrize("case", ["short", "pending", "retiring", "retired", "empty", "kid", "ref"])
def test_rotation_refusals_do_not_change_the_ring(case: str) -> None:
    """Short publication, inactive tails and reused identities refuse the entire pure plan."""
    record = initial_record(PUBLIC, "first.pem", AT)
    records = (record,)
    active_from = AT + MIN_PUBLICATION_LEAD
    key, ref = SUCCESSOR, "second.pem"
    reason = "pending_key_exists"
    if case == "short":
        active_from -= TICK
        reason = "lead_too_short"
    elif case == "pending":
        records = (replace(record, active_from=AT + TICK),)
    elif case in {"retiring", "retired"}:
        records = (
            replace(
                record,
                active_from=AT - timedelta(days=1),
                retired_at=AT if case == "retiring" else AT - RETENTION,
            ),
        )
    elif case == "empty":
        records = ()
    elif case in {"kid", "ref"}:
        key = PUBLIC if case == "kid" else SUCCESSOR
        ref = "first.pem" if case == "ref" else "second.pem"
        reason = "key_already_registered"
    ring = KeyRing(records, {}, AT)
    with pytest.raises(RotationRefused) as failure:
        plan_rotation(ring, key, ref, active_from, AT)
    assert failure.value.context["reason"] == reason
    assert ring.records == records


def test_ring_owns_containers_and_orders_publication_and_algorithms() -> None:
    """Changing input containers cannot change sorted public output or loaded signing keys."""
    rsa_public = PublicSigningKey.from_private(rsa.generate_private_key(65537, 2048))
    first = SigningKeyRecord(rsa_public, "rsa.pem", AT - TICK, AT)
    active = initial_record(PUBLIC, "first.pem", AT)
    pending = initial_record(SUCCESSOR, "second.pem", AT + MIN_PUBLICATION_LEAD)
    records = [pending, active, first]
    private_keys = {PUBLIC.kid: PRIVATE}
    ring = KeyRing(records, private_keys, AT)
    records.clear()
    private_keys.clear()
    assert ring.records == (first, active, pending)
    assert ring.signer(AT) == (active, PRIVATE)
    assert ring.jwks(AT) == {"keys": [rsa_public.as_jwk(), PUBLIC.as_jwk(), SUCCESSOR.as_jwk()]}
    assert ring.algorithms(AT) == ("ES256", "RS256")
    assert ring.algorithms(AT + RETENTION) == ("ES256",)
    assert "private_keys" not in repr(ring)
    with pytest.raises(TypeError):
        ring.private_keys[PUBLIC.kid] = SUCCESSOR_PRIVATE
    with pytest.raises(FrozenInstanceError):
        ring.records = ()


def test_empty_ring_has_no_public_keys_or_algorithms() -> None:
    """An empty snapshot publishes an empty JWKS and cannot resolve a verification key."""
    ring = KeyRing((), {}, AT)
    assert ring.jwks(AT) == {"keys": []}
    assert ring.algorithms(AT) == ()
    assert ring.verification_key(PUBLIC.kid, AT) is None


def test_publication_and_retention_constants_cover_all_caches_and_tokens() -> None:
    """Publication precedes stale signers and cached JWKS; retention covers maximum token lifetime."""
    assert TOKEN_TTL_MAX == timedelta(hours=1)
    assert VERIFY_LEEWAY == timedelta(seconds=30)
    assert RETENTION == TOKEN_TTL_MAX + VERIFY_LEEWAY
    assert REFRESH_INTERVAL == timedelta(seconds=60)
    assert MAX_RING_AGE == JWKS_MAX_AGE == timedelta(minutes=5)
    assert MIN_PUBLICATION_LEAD == timedelta(minutes=10)
    assert MIN_PUBLICATION_LEAD > MAX_RING_AGE
    assert MIN_PUBLICATION_LEAD >= REFRESH_INTERVAL + JWKS_MAX_AGE
