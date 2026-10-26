"""Signing keys preserve immutable identity, publication windows and rotation continuity."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    FileSigningKeySource,
    HuronKeys,
    KeyRing,
    KeyState,
    PrivateSigningKey,
    PublicSigningKey,
    SigningKeyRecord,
    SigningKeySource,
    initial_record,
    jwk_thumbprint,
    plan_rotation,
)
from huron.core.security.errors import RotationRefused, SigningKeyUnavailable
from tests.lake_tokens import (
    TEST_EPOCH,
    TEST_KEY,
    TEST_KEY_REF,
    TEST_KID,
    TEST_RECORD,
    InMemorySigningKeySource,
    PausedSigningKeyReader,
    ScriptedSigningKeyReader,
)
from tests.unit.support import FakeClock

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
    assert timedelta(hours=1) == TOKEN_TTL_MAX
    assert timedelta(seconds=30) == VERIFY_LEEWAY
    assert RETENTION == TOKEN_TTL_MAX + VERIFY_LEEWAY
    assert timedelta(seconds=60) == REFRESH_INTERVAL
    assert MAX_RING_AGE == JWKS_MAX_AGE == timedelta(minutes=5)
    assert timedelta(minutes=10) == MIN_PUBLICATION_LEAD
    assert MIN_PUBLICATION_LEAD > MAX_RING_AGE
    assert MIN_PUBLICATION_LEAD >= REFRESH_INTERVAL + JWKS_MAX_AGE


def test_shared_key_identity_is_pinned() -> None:
    """The fixed fixture thumbprint changes only with an intentional fixture identity change."""
    assert PublicSigningKey.from_private(TEST_KEY).kid == TEST_KID
    assert initial_record(TEST_RECORD.key, TEST_KEY_REF, TEST_EPOCH) == TEST_RECORD


@pytest.mark.parametrize(
    "format", [serialization.PrivateFormat.PKCS8, serialization.PrivateFormat.TraditionalOpenSSL]
)
@pytest.mark.parametrize("algorithm", ["ES256", "RS256"])
def test_file_source_follows_secret_symlinks_without_caching(
    tmp_path: Path, format: serialization.PrivateFormat, algorithm: str
) -> None:
    """Secret-volume symlinks load both PEM formats and each load observes the current file."""
    directory = tmp_path / "keys"
    data = directory / "..data"
    data.mkdir(parents=True)
    pem = data / TEST_KEY_REF
    (directory / TEST_KEY_REF).symlink_to(Path("..data") / TEST_KEY_REF)
    private = TEST_KEY if algorithm == "ES256" else rsa.generate_private_key(65537, 2048)
    pem.write_bytes(
        private.private_bytes(serialization.Encoding.PEM, format, serialization.NoEncryption())
    )
    pem.chmod(0o644)
    source: SigningKeySource = FileSigningKeySource(directory)
    assert PublicSigningKey.from_private(
        source.load(TEST_KEY_REF)
    ) == PublicSigningKey.from_private(private)
    pem.write_bytes(b"changed")
    with pytest.raises(SigningKeyUnavailable) as failure:
        source.load(TEST_KEY_REF)
    assert failure.value.context == {"private_ref": TEST_KEY_REF, "reason": "not_pem"}


@pytest.mark.parametrize(
    "ref", ["../x.pem", "", ".", "..", "/x.pem", "a/b", "a\\b", "a\n", "é.pem", "a b"]
)
def test_file_source_refuses_non_bare_references(tmp_path: Path, ref: str) -> None:
    """Only the catalog's ASCII filename grammar is accepted."""
    with pytest.raises(SigningKeyUnavailable) as failure:
        FileSigningKeySource(tmp_path).load(ref)
    assert failure.value.context == {"private_ref": ref, "reason": "bad_ref"}


@pytest.mark.parametrize(
    "case,reason",
    [
        ("escape", "outside_directory"),
        ("missing", "missing"),
        ("directory", "unreadable"),
        ("cycle", "unreadable"),
        ("nonpem", "not_pem"),
        ("oversized", "not_pem"),
        ("encrypted", "encrypted"),
        ("p384", "unsupported_key"),
        ("rsa1024", "unsupported_key"),
        ("ed25519", "unsupported_key"),
    ],
)
def test_file_source_reports_safe_failure_reasons(tmp_path: Path, case: str, reason: str) -> None:
    """Read and key-validation failures disclose only the reference and stable reason."""
    directory = tmp_path / "keys"
    directory.mkdir()
    path = directory / TEST_KEY_REF
    if case == "escape":
        path.symlink_to(tmp_path / "outside.pem")
    elif case == "directory":
        path.mkdir()
    elif case == "cycle":
        path.symlink_to(TEST_KEY_REF)
    elif case in {"nonpem", "oversized"}:
        path.write_bytes(b"x" * (16385 if case == "oversized" else 32))
    elif case != "missing":
        key = {
            "encrypted": lambda: TEST_KEY,
            "p384": lambda: ec.derive_private_key(1, ec.SECP384R1()),
            "rsa1024": lambda: rsa.generate_private_key(65537, 1024),
            "ed25519": ed25519.Ed25519PrivateKey.generate,
        }[case]()
        encryption = (
            serialization.BestAvailableEncryption(b"test-password")
            if case == "encrypted"
            else serialization.NoEncryption()
        )
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption
            )
        )
    with pytest.raises(SigningKeyUnavailable) as failure:
        FileSigningKeySource(directory).load(TEST_KEY_REF)
    assert failure.value.context == {"private_ref": TEST_KEY_REF, "reason": reason}


@pytest.mark.parametrize(
    "case", ["store", "empty", "pending_missing", "active_missing", "thumbprint", "algorithm"]
)
async def test_startup_refuses_incomplete_or_invalid_key_sets(case: str) -> None:
    """Startup never launches a loop with missing, unavailable or inconsistent signing material."""
    records = [TEST_RECORD]
    source = InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY})
    error = RuntimeError("store unavailable") if case == "store" else None
    if case == "empty":
        records = []
    elif case == "pending_missing":
        records.append(initial_record(SUCCESSOR, "pending.pem", TEST_EPOCH + MIN_PUBLICATION_LEAD))
    elif case == "active_missing":
        source.keys.clear()
    elif case == "thumbprint":
        source.keys[TEST_KEY_REF] = PRIVATE
    elif case == "algorithm":
        records = [replace(TEST_RECORD, key=replace(TEST_RECORD.key, alg="RS256"))]
    reader = ScriptedSigningKeyReader(records, error)
    keys = HuronKeys(reader, source, FakeClock(TEST_EPOCH))
    with pytest.raises(RuntimeError if error else SigningKeyUnavailable) as failure:
        async with keys:
            pytest.fail("Invalid startup entered the context")
    assert keys.ring.records == ()
    assert reader.calls == 1
    if case in {"pending_missing", "active_missing", "thumbprint", "algorithm"}:
        assert failure.value.context["kid"] == records[-1].key.kid
        assert failure.value.context["private_ref"] == records[-1].private_ref
    await keys.__aexit__()


async def test_refresh_reuses_loaded_keys_and_withdraws_removed_records() -> None:
    """Refreshing retains private identity while observing row updates, retirement and withdrawal."""
    clock = FakeClock(TEST_EPOCH)
    source = InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY, "pending.pem": SUCCESSOR_PRIVATE})
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(reader, source, clock)
    first = await keys.refresh()
    source.keys.clear()
    clock.advance(TICK)
    assert (await keys.refresh()).signer(clock.now()) == (TEST_RECORD, TEST_KEY)
    assert first.loaded_at == TEST_EPOCH
    reader.records = [replace(TEST_RECORD, retired_at=clock.now())]
    retiring = await keys.refresh()
    assert retiring.private_keys == {}
    assert retiring.verification_key(TEST_KID, clock.now()) == TEST_RECORD.key
    reader.records.clear()
    assert (await keys.refresh()).records == ()
    assert first.records == (TEST_RECORD,)


async def test_runtime_store_failure_preserves_snapshot_until_signing_becomes_stale() -> None:
    """A failed store read leaves verification available but cannot extend signing freshness."""
    clock = FakeClock(TEST_EPOCH)
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(reader, InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}), clock)
    async with keys as running:
        assert running is keys
        ring = keys.ring
        reader.exception = RuntimeError("store unavailable")
        with pytest.raises(RuntimeError, match="store unavailable"):
            await keys.refresh()
        assert keys.ring is ring
        clock.advance(MAX_RING_AGE + TICK)
        with pytest.raises(SigningKeyUnavailable) as failure:
            keys.ring.signer(clock.now())
        assert failure.value.context == {"reason": "stale"}
        assert keys.ring.verification_key(TEST_KID, clock.now()) == TEST_RECORD.key


@pytest.mark.parametrize("mismatch", [False, True])
async def test_pending_key_failure_is_logged_and_retried_without_blocking_current_signer(
    caplog: pytest.LogCaptureFixture, mismatch: bool
) -> None:
    """A runtime pending failure keeps public discovery, and later successful loading repairs it."""
    clock = FakeClock(TEST_EPOCH)
    source = InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY})
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(reader, source, clock)
    async with keys:
        switch = TEST_EPOCH + MIN_PUBLICATION_LEAD
        reader.records = [
            replace(TEST_RECORD, retired_at=switch),
            initial_record(SUCCESSOR, "pending.pem", switch),
        ]
        if mismatch:
            source.keys["pending.pem"] = TEST_KEY
        ring = await keys.refresh()
        assert ring.signer(TEST_EPOCH)[1] is TEST_KEY
        assert ring.verification_key(SUCCESSOR.kid, TEST_EPOCH) == SUCCESSOR
        assert SUCCESSOR.kid not in ring.private_keys
        assert SUCCESSOR.kid in caplog.text and "pending.pem" in caplog.text
        clock.set(switch)
        with pytest.raises(SigningKeyUnavailable):
            await keys.refresh()
        assert keys.ring is ring
        # A refresh shortly before switching makes unloaded-key refusal distinct from staleness.
        clock.set(switch - TICK)
        await keys.refresh()
        with pytest.raises(SigningKeyUnavailable) as failure:
            keys.ring.signer(switch)
        assert failure.value.context["reason"] == "not_loaded"
        source.keys["pending.pem"] = SUCCESSOR_PRIVATE
        clock.set(switch)
        assert (await keys.refresh()).signer(switch)[1] is SUCCESSOR_PRIVATE


async def test_refresh_rechecks_reused_key_algorithm() -> None:
    """Reusing cached private material does not bypass validation of changed registration metadata."""
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(
        reader, InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}), FakeClock(TEST_EPOCH)
    )
    ring = await keys.refresh()
    reader.records = [replace(TEST_RECORD, key=replace(TEST_RECORD.key, alg="RS256"))]
    with pytest.raises(SigningKeyUnavailable) as failure:
        await keys.refresh()
    assert failure.value.context["reason"] == "key_mismatch"
    assert keys.ring is ring


async def test_refresh_loop_retries_failures_and_stops_on_context_exit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The millisecond test interval reaches the loop, logs failures and shuts it down fully."""
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(
        reader,
        InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}),
        FakeClock(TEST_EPOCH),
        refresh_interval=timedelta(milliseconds=1),
    )
    async with keys:
        reader.exception = RuntimeError("scripted refresh failure")
        async with asyncio.timeout(2):
            while reader.calls < 2:
                await asyncio.sleep(0.001)
        assert "Signing key refresh failed" in caplog.text
        reader.exception = None
        async with asyncio.timeout(2):
            while reader.calls < 3:
                await asyncio.sleep(0.001)
    calls = reader.calls
    await asyncio.sleep(0.005)
    assert reader.calls == calls


async def test_concurrent_refreshes_publish_serial_snapshots() -> None:
    """Concurrent refresh callers serialize persistence reads and publish detached snapshots."""
    reader = PausedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(
        reader, InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}), FakeClock(TEST_EPOCH)
    )
    first = asyncio.create_task(keys.refresh())
    await reader.entered.wait()
    second = asyncio.create_task(keys.refresh())
    await asyncio.sleep(0)
    assert keys.ring.records == ()
    assert not first.done() and not second.done()
    reader.release.set()
    snapshots = await asyncio.gather(first, second)
    assert reader.calls == 2
    assert reader.max_inflight == 1
    assert snapshots[0] is not snapshots[1]
    assert keys.ring is snapshots[1]
    assert all(ring.signer(TEST_EPOCH) == (TEST_RECORD, TEST_KEY) for ring in snapshots)


async def test_context_exit_awaits_an_inflight_refresh_cancellation() -> None:
    """Shutdown cancels an in-flight reader and waits for its cleanup before returning."""
    reader = PausedSigningKeyReader([TEST_RECORD])
    reader.release.set()
    keys = HuronKeys(
        reader,
        InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}),
        FakeClock(TEST_EPOCH),
        refresh_interval=timedelta(milliseconds=1),
    )
    async with keys:
        reader.release.clear()
        reader.entered.clear()
        reader.finished.clear()
        async with asyncio.timeout(2):
            await reader.entered.wait()
        assert not reader.finished.is_set()
    assert reader.finished.is_set()
    assert reader.calls == 1


@pytest.mark.parametrize("size", [16 * 1024, 16 * 1024 + 1])
def test_file_source_enforces_the_exact_read_limit(tmp_path: Path, size: int) -> None:
    """Otherwise valid PEM loads at the size limit and is refused one byte beyond it."""
    pem = TEST_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (tmp_path / TEST_KEY_REF).write_bytes(pem.ljust(size, b"\n"))
    source = FileSigningKeySource(tmp_path)
    if size == 16 * 1024:
        assert PublicSigningKey.from_private(source.load(TEST_KEY_REF)) == TEST_RECORD.key
    else:
        with pytest.raises(SigningKeyUnavailable) as failure:
            source.load(TEST_KEY_REF)
        assert failure.value.context == {"private_ref": TEST_KEY_REF, "reason": "not_pem"}
