"""Real signatures enforce the lake identity and deterministic validity contract."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from huron.core.foundation.errors import AuthError
from huron.core.security.broker import (
    MAX_RING_AGE,
    RETENTION,
    CatalogRef,
    ClaimedRole,
    Grant,
    Grants,
    HuronClaims,
    HuronKeys,
    HuronTokenIssuer,
    HuronTokenVerifier,
    PublicSigningKey,
    Role,
    SigningKeyRecord,
)
from huron.core.security.errors import SigningKeyUnavailable
from tests.lake_tokens import (
    TEST_ISSUER,
    TEST_KEY,
    TEST_KEY_REF,
    TEST_KID,
    TEST_RECORD,
    InMemorySigningKeySource,
    ScriptedSigningKeyReader,
    mint,
    refreshed_test_keys,
)
from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit
AT = datetime(2026, 10, 23, 12, tzinfo=UTC)


def payload(**changes: object) -> dict[str, object]:
    """Return a valid identity payload with explicit hostile-field overrides."""
    return {
        "iss": TEST_ISSUER,
        "sub": "karl",
        "aud": ["huron-api"],
        "iat": int(AT.timestamp()),
        "exp": int(AT.timestamp()) + 3600,
        "groups": ["helio-scientists"],
        "roles": ["PRINCIPAL_ROLE:heliophysics.catalog_contributor"],
        **changes,
    }


def signed(claims: dict[str, object], **headers: object) -> str:
    """Sign arbitrary claims to exercise verification independently of issuance."""
    return jwt.encode(claims, TEST_KEY, algorithm="ES256", headers={"kid": TEST_KID, **headers})


async def test_golden_token() -> None:
    """The stored signature pins the public wire contract and key thumbprint."""
    clock = FakeClock(AT + timedelta(seconds=30))
    keys = await refreshed_test_keys(clock)
    token = GOLDEN_TOKEN
    assert jwt.get_unverified_header(token) == {"alg": "ES256", "kid": TEST_KID, "typ": "JWT"}
    assert HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(token) == HuronClaims(
        TEST_ISSUER,
        "karl",
        ("huron-api",),
        (ClaimedRole(Role.CATALOG_CONTRIBUTOR, "heliophysics"),),
        ("helio-scientists",),
        AT,
        AT + timedelta(hours=1),
        TEST_KID,
    )


@pytest.mark.parametrize("role", list(Role))
async def test_issuance_round_trip(role: Role) -> None:
    """Every valid role scope preserves grants order and sorted directory groups."""
    clock = FakeClock(AT + timedelta(microseconds=999999))
    keys = await refreshed_test_keys(clock)
    catalog = None if not role.catalog_scoped else CatalogRef(UUID(int=1), "helio")
    grants = Grants("karl", [Grant(role, catalog)])
    issuer = HuronTokenIssuer(
        keys,
        issuer=TEST_ISSUER,
        audience=("huron-api", "other"),
        ttl=timedelta(hours=1),
        clock=clock,
    )
    issued = issuer.issue("karl", frozenset({"z", "a", "z"}), grants)
    assert (
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(issued.token)
        == issued.claims
    )
    assert issued.claims.groups == ("a", "z")
    assert issued.claims.roles == tuple(ClaimedRole.of(g) for g in grants)
    assert issued.claims.iat == AT
    assert jwt.decode(issued.token, options={"verify_signature": False})["aud"] == [
        "huron-api",
        "other",
    ]
    assert (
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(mint(keys, clock)).roles
        == ()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("iss", "wrong"),
        ("aud", ["wrong"]),
        ("aud", "wrong"),
        ("aud", "huron-api"),
        ("aud", ["huron-api", 1]),
        ("sub", ""),
        ("sub", 1),
        ("groups", "group"),
        ("groups", [""]),
        ("groups", [1]),
        ("roles", "catalog_reader"),
        ("roles", ["PRINCIPAL_ROLE:helio_catalog_contributor"]),
        ("roles", [1]),
        *(
            ("roles", ["PRINCIPAL_ROLE:" + body])
            for body in (
                "reader",
                "developer",
                "project_admin",
                "organization_admin",
                "platform_owner",
                "catalog_reader",
                "catalog_contributor",
                "catalog_owner",
                "helio.administrator",
            )
        ),
        ("iat", int(AT.timestamp()) + 31),
        ("exp", int(AT.timestamp()) - 31),
        ("exp", int(AT.timestamp()) + 3601),
        ("exp", int(AT.timestamp())),
        ("iat", True),
        ("exp", True),
        ("iat", 1.2),
        ("exp", "123"),
        ("iat", None),
        ("exp", None),
    ],
)
async def test_invalid_claims_are_one_authentication_error(field: str, value: object) -> None:
    """Malformed signed claims never become accepted identity or a server error."""
    clock = FakeClock(AT)
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    with pytest.raises(AuthError) as caught:
        verifier.verify(signed(payload(**{field: value})))
    assert caught.value.code == "INVALID_CREDENTIAL"


@pytest.mark.parametrize("field", ["iss", "sub", "aud", "iat", "exp", "groups", "roles"])
async def test_required_claims(field: str) -> None:
    """Every required identity field must exist even with a valid signature."""
    clock = FakeClock(AT)
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    claims = payload()
    del claims[field]
    with pytest.raises(AuthError):
        verifier.verify(signed(claims))


@pytest.mark.parametrize("kid", [None, "", 1, [], {}, "unknown"])
async def test_unknown_key_precedes_signature_validation(kid: object) -> None:
    """Hostile key identifiers are refused before an intentionally invalid signature."""
    import base64
    import json

    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "ES256", "kid": kid}).encode())
        .rstrip(b"=")
        .decode()
    )
    clock = FakeClock(AT)
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    with pytest.raises(AuthError, match="kid|signing key|Key ID"):
        verifier.verify(header + ".e30.AAAA")


async def test_hostile_headers_and_corrupted_payload() -> None:
    """Algorithm confusion, missing headers and altered bytes are refused."""
    clock = FakeClock(AT)
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tokens = [
        jwt.encode(payload(), rsa_key, algorithm="RS256", headers={"kid": TEST_KID}),
        jwt.encode(payload(), "", algorithm="none", headers={"kid": TEST_KID}),
        jwt.encode(
            payload(), str(TEST_RECORD.key.as_jwk()), algorithm="HS256", headers={"kid": TEST_KID}
        ),
        jwt.encode(payload(), TEST_KEY, algorithm="ES256"),
        "garbage",
    ]
    pieces = signed(payload()).split(".")
    pieces[1] = pieces[1][:-1] + ("B" if pieces[1][-1] != "B" else "C")
    tokens.append(".".join(pieces))
    for token in tokens:
        with pytest.raises(AuthError) as caught:
            verifier.verify(token)
        assert caught.value.code == "INVALID_CREDENTIAL"


@pytest.mark.parametrize("offset,accepted", [(29, True), (30, False), (31, False)])
async def test_expiry_boundary(offset: int, accepted: bool) -> None:
    """Expiration leeway has an exclusive upper bound under the injected clock."""
    clock = FakeClock(AT + timedelta(seconds=3600 + offset))
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    if accepted:
        assert verifier.verify(signed(payload())).sub == "karl"
    else:
        with pytest.raises(AuthError):
            verifier.verify(signed(payload()))


async def test_pending_and_retiring_keys() -> None:
    """Published pending keys verify, while retirement expires exactly at retention."""
    clock = FakeClock(AT)
    for row in [
        replace(TEST_RECORD, active_from=AT + timedelta(hours=1)),
        replace(TEST_RECORD, retired_at=AT - RETENTION + timedelta(microseconds=1)),
    ]:
        keys = HuronKeys(
            ScriptedSigningKeyReader([row]),
            InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}),
            clock,
        )
        await keys.refresh()
        assert (
            HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(signed(payload())).sub
            == "karl"
        )
    clock.advance(timedelta(microseconds=1))
    with pytest.raises(AuthError, match="retired"):
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(signed(payload()))


@pytest.mark.parametrize(
    "issuer,audience,seconds",
    [
        (TEST_ISSUER + "/", ("huron-api",), 60),
        (TEST_ISSUER + "?q=1", ("huron-api",), 60),
        (TEST_ISSUER + "#f", ("huron-api",), 60),
        (TEST_ISSUER, (), 60),
        (TEST_ISSUER, ("huron-api", ""), 60),
        (TEST_ISSUER, ("huron-api",), 59),
        (TEST_ISSUER, ("huron-api",), 3601),
    ],
)
async def test_constructor_refusals(issuer: str, audience: tuple[str, ...], seconds: int) -> None:
    """Composition rejects invalid issuer, audience and token lifetime settings."""
    clock = FakeClock(AT)
    keys = await refreshed_test_keys(clock)
    with pytest.raises(ValueError):
        HuronTokenIssuer(
            keys, issuer=issuer, audience=audience, ttl=timedelta(seconds=seconds), clock=clock
        )


async def test_empty_identity_and_stale_signer() -> None:
    """Programming errors fail locally and stale signing material remains unavailable."""
    clock = FakeClock(AT)
    keys = await refreshed_test_keys(clock)
    issuer = HuronTokenIssuer(
        keys, issuer=TEST_ISSUER, audience=("huron-api",), ttl=timedelta(seconds=60), clock=clock
    )
    for subject, groups in [("", frozenset()), ("karl", frozenset({""}))]:
        with pytest.raises(ValueError):
            issuer.issue(subject, groups, Grants(subject, ()))
    assert issuer.issue("karl", frozenset(), Grants("karl", ())).claims.groups == ()
    clock.advance(MAX_RING_AGE + timedelta(microseconds=1))
    with pytest.raises(SigningKeyUnavailable):
        issuer.issue("karl", frozenset(), Grants("karl", ()))


async def test_rsa_signer_and_ignored_extra_claims() -> None:
    """RSA records select RS256 and unrecognized claims do not alter validity."""
    clock = FakeClock(AT)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    record = SigningKeyRecord(PublicSigningKey.from_private(key), "rsa.pem", AT, None)
    keys = HuronKeys(
        ScriptedSigningKeyReader([record]), InMemorySigningKeySource({"rsa.pem": key}), clock
    )
    await keys.refresh()
    assert (
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(mint(keys, clock)).kid
        == record.key.kid
    )
    keys = await refreshed_test_keys(clock)
    assert (
        HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock)
        .verify(
            signed(payload(nbf=99999999999, jti=123, scope={"unrecognized": True}), typ="other")
        )
        .sub
        == "karl"
    )


GOLDEN_TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6InpYOWlIWWJQSzhpaE5fTUZmUVBRTUlFNjE4Q0xnWW1FRkF3ZVhqczF2Sm8iLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL2h1cm9uLnRlc3QiLCJzdWIiOiJrYXJsIiwiYXVkIjpbImh1cm9uLWFwaSJdLCJpYXQiOjE3OTI3NTY4MDAsImV4cCI6MTc5Mjc2MDQwMCwiZ3JvdXBzIjpbImhlbGlvLXNjaWVudGlzdHMiXSwicm9sZXMiOlsiUFJJTkNJUEFMX1JPTEU6aGVsaW9waHlzaWNzLmNhdGFsb2dfY29udHJpYnV0b3IiXX0.CziXWvFYBKeLVV-3j2MGlBZg89mHsanERvjU6wkyRdc_l6zuryB0nCGwLCCtk6FWpDxne8zdRzdr1TTgYWNYbg"


def test_shared_time_rules_reject_unrepresentable_dates() -> None:
    """Unbounded external lifetimes cannot escape as platform timestamp errors."""
    from huron.core.security.broker.tokens import _validate_times

    with pytest.raises(ValueError, match="supported range"):
        _validate_times({"iat": int(AT.timestamp()), "exp": 10**100}, AT)


async def test_combined_grants_and_store_free_operations() -> None:
    """Normalized organization and catalog claims are ordered without reading persistence."""
    clock = FakeClock(AT)
    reader = ScriptedSigningKeyReader([TEST_RECORD])
    keys = HuronKeys(reader, InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY}), clock)
    await keys.refresh()
    reader.exception = RuntimeError("store unavailable")
    helio = CatalogRef(UUID(int=1), "heliophysics")
    astro = CatalogRef(UUID(int=2), "astro")
    grants = Grants(
        "karl",
        [
            Grant(Role.CATALOG_READER, helio),
            Grant(Role.CATALOG_OWNER, helio),
            Grant(Role.CATALOG_CONTRIBUTOR, astro),
            Grant(Role.ADMINISTRATOR, None),
        ],
    )
    token = mint(keys, clock, grants=grants)
    claims = HuronTokenVerifier(keys, issuer=TEST_ISSUER, clock=clock).verify(token)
    assert tuple(map(str, claims.roles)) == (
        "PRINCIPAL_ROLE:administrator",
        "PRINCIPAL_ROLE:astro.catalog_contributor",
        "PRINCIPAL_ROLE:heliophysics.catalog_owner",
    )
    assert reader.calls == 1


@pytest.mark.parametrize("seconds", [29, 30])
async def test_future_issuance_leeway(seconds: int) -> None:
    """An issuance time exactly at the skew allowance is accepted."""
    clock = FakeClock(AT)
    verifier = HuronTokenVerifier(await refreshed_test_keys(clock), issuer=TEST_ISSUER, clock=clock)
    assert verifier.verify(
        signed(payload(iat=int(AT.timestamp()) + seconds))
    ).iat == AT + timedelta(seconds=seconds)
