"""Company signature verification, remote failures and clock-controlled key caching."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import jwt
import pytest

from huron.core.foundation.errors import AuthError, DependencyUnavailable
from huron.core.security.broker import CompanyTokenVerifier
from huron.core.security.broker.exchange import JWKS_REFETCH_FLOOR, JWKS_TTL

if TYPE_CHECKING:
    from tests.fakes.oidc_issuer import FakeCompanyIdp
    from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit


def _verifier(
    http: httpx.AsyncClient, issuer: FakeCompanyIdp, clock: FakeClock
) -> CompanyTokenVerifier:
    return CompanyTokenVerifier(
        http, issuer=issuer.issuer, audiences=frozenset({issuer.client_id}), clock=clock
    )


def _header(token: str, **values: object) -> str:
    header, payload, signature = token.split(".")
    changed = jwt.get_unverified_header(token)
    changed.update(values)
    encoded = base64.urlsafe_b64encode(json.dumps(changed).encode()).decode().rstrip("=")
    return ".".join((encoded, payload, signature))


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
async def test_verified_claims_are_unchanged_and_client_stays_open(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    algorithm: str,
) -> None:
    """Real signatures verify while uninterpreted optional claims retain their shape."""
    if algorithm == "ES256":
        fake_issuer.rotate_key()
    token = fake_issuer.id_token(
        "karl",
        claims={
            "aud": [fake_issuer.client_id, "other-client"],
            "sub": 123,
            "jti": [],
            "nbf": "not interpreted",
            "groups": {"opaque": True},
        },
    )
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        verifier = _verifier(http, fake_issuer, clock)
        assert fake_issuer.hits["discovery"] == 0
        assert await verifier.verify(token) == jwt.decode(
            token, options={"verify_signature": False}
        )
        assert not http.is_closed


@pytest.mark.parametrize("claim", ["iss", "aud", "exp", "iat"])
async def test_required_claims(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    claim: str,
) -> None:
    """Every required claim must be present even with a genuine signature."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(AuthError):
            await _verifier(http, fake_issuer, clock).verify(
                fake_issuer.id_token("karl", drop=[claim])
            )


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.test"},
        {"aud": "other"},
        {"aud": []},
        {"iat": True},
        {"exp": 1.5},
        {"iat": "1"},
        {"exp": 0},
        {"iat": 9999999999},
        {"iat": 3, "exp": 2},
    ],
)
async def test_invalid_signed_claims(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    claims: dict[str, object],
) -> None:
    """Issuer, audience and integer validity rules reject untrusted tokens."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(AuthError):
            await _verifier(http, fake_issuer, clock).verify(
                fake_issuer.id_token("karl", claims=claims)
            )


@pytest.mark.parametrize(
    "change",
    [
        "malformed",
        "no_kid",
        "bad_alg",
        "unknown",
        "forged",
        "empty_kid",
        "numeric_kid",
        "rsa_as_ec",
        "ec_as_rsa",
    ],
)
async def test_invalid_headers_and_signatures(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    change: str,
) -> None:
    """Malformed headers and unverifiable signatures fail authentication."""
    if change == "ec_as_rsa":
        fake_issuer.rotate_key()
    token = fake_issuer.id_token("karl", forged=change == "forged")
    if change == "malformed":
        token = "not a JWS"
    elif change == "no_kid":
        token = "e30." + token.split(".", 1)[1]
    elif change in {"bad_alg", "unknown", "empty_kid", "numeric_kid", "rsa_as_ec", "ec_as_rsa"}:
        token = _header(
            token,
            **{
                "bad_alg": {"alg": "HS256"},
                "rsa_as_ec": {"alg": "ES256"},
                "ec_as_rsa": {"alg": "RS256"},
                "unknown": {"kid": "absent"},
                "empty_kid": {"kid": ""},
                "numeric_kid": {"kid": 12},
            }[change],
        )
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(AuthError) as raised:
            await _verifier(http, fake_issuer, clock).verify(token)
    assert raised.value.code == "INVALID_CREDENTIAL"


@pytest.mark.parametrize("endpoint", ["discovery", "jwks"])
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("timeout", "timeout"),
        ("unreachable", "unreachable"),
        (500, "status"),
        ("malformed", "malformed"),
    ],
)
async def test_remote_failures(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    endpoint: str,
    failure: str | int,
    reason: str,
) -> None:
    """Discovery and JWKS faults retain the dependency and stable failure reason."""
    fake_issuer.inject(endpoint, failure)
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(DependencyUnavailable) as raised:
            await _verifier(http, fake_issuer, clock).verify(fake_issuer.id_token("karl"))
    assert raised.value.context == {"dependency": "company_idp", "reason": reason}
    assert raised.value.retry_after == 30


async def test_discovery_issuer_mismatch(
    fake_issuer: FakeCompanyIdp, fake_issuer_transport: httpx.ASGITransport, clock: FakeClock
) -> None:
    """Discovery from another issuer is an unavailable dependency."""
    fake_issuer.inject("discovery", "issuer_mismatch")
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(DependencyUnavailable) as raised:
            await _verifier(http, fake_issuer, clock).verify(fake_issuer.id_token("karl"))
    assert raised.value.context == {"dependency": "company_idp", "reason": "issuer_mismatch"}


async def test_concurrent_discovery_rotation_and_refetch_floor(
    fake_issuer: FakeCompanyIdp, fake_issuer_transport: httpx.ASGITransport, clock: FakeClock
) -> None:
    """Concurrent first use shares discovery; random kids cannot amplify refreshes."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        verifier = _verifier(http, fake_issuer, clock)
        token = fake_issuer.id_token("karl")
        await asyncio.gather(*(verifier.verify(token) for _ in range(8)))
        assert fake_issuer.hits["discovery"] == fake_issuer.hits["jwks"] == 1
        fake_issuer.rotate_key()
        await verifier.verify(fake_issuer.id_token("karl"))
        assert fake_issuer.hits["jwks"] == 2
        for kid in ["unknown1", "unknown2"]:
            with pytest.raises(AuthError):
                await verifier.verify(_header(token, kid=kid))
        assert fake_issuer.hits["jwks"] == 2
        clock.advance(JWKS_REFETCH_FLOOR)
        with pytest.raises(AuthError):
            await verifier.verify(_header(token, kid="unknown3"))
        assert fake_issuer.hits["jwks"] == 3
        clock.advance(JWKS_TTL)
        await verifier.verify(fake_issuer.id_token("karl"))
        assert fake_issuer.hits["jwks"] == 4
        assert fake_issuer.hits["discovery"] == 1


async def test_failed_refresh_keeps_fresh_keys_and_bounds_attempts(
    fake_issuer: FakeCompanyIdp, fake_issuer_transport: httpx.ASGITransport, clock: FakeClock
) -> None:
    """An outage preserves fresh keys while unknown-key failures consume the floor."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        verifier = _verifier(http, fake_issuer, clock)
        token = fake_issuer.id_token("karl")
        await verifier.verify(token)
        fake_issuer.inject("jwks", "timeout")
        with pytest.raises(DependencyUnavailable):
            await verifier.verify(_header(token, kid="new"))
        await verifier.verify(token)
        with pytest.raises(AuthError):
            await verifier.verify(_header(token, kid="other"))
        assert fake_issuer.hits["jwks"] == 2
        clock.advance(JWKS_REFETCH_FLOOR)
        with pytest.raises(DependencyUnavailable):
            await verifier.verify(_header(token, kid="newer"))
        assert fake_issuer.hits["jwks"] == 3
        clock.advance(JWKS_TTL)
        with pytest.raises(DependencyUnavailable):
            await verifier.verify(fake_issuer.id_token("karl"))
        fake_issuer.inject("jwks", None)
        clock.advance(JWKS_REFETCH_FLOOR)
        await verifier.verify(fake_issuer.id_token("karl"))


@pytest.mark.parametrize(
    ("issuer", "audiences"),
    [
        *[
            (url, frozenset({"cli"}))
            for url in [
                "https://idp.test:notaport",
                "https://idp.test:0",
                "https://idp.test/\x00",
                "https://idp.test:99999",
                "http://user@",
                "https:///nohost",
                "https://[broken",
            ]
        ],
        ("relative", frozenset({"cli"})),
        ("https://idp.test/", frozenset({"cli"})),
        ("https://idp.test?x", frozenset({"cli"})),
        ("https://idp.test#x", frozenset({"cli"})),
        ("https://idp.test", frozenset()),
        ("https://idp.test", frozenset({""})),
    ],
)
async def test_constructor_refuses_invalid_policy(
    clock: FakeClock,
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    issuer: str,
    audiences: frozenset[str],
) -> None:
    """Invalid trust policy fails without network traffic."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(ValueError):
            CompanyTokenVerifier(http, issuer=issuer, audiences=audiences, clock=clock)
    assert not any(fake_issuer.hits.values())


@pytest.mark.parametrize(
    ("endpoint", "document"),
    [
        *[
            ("discovery", {"issuer": "https://idp.test/realms/company", "jwks_uri": url})
            for url in [
                "https://idp.test:notaport/certs",
                "https://idp.test:0/certs",
                "https://idp.test/\x00",
                "https://idp.test:99999/certs",
                "http://user@/certs",
                "https:///certs",
            ]
        ],
        ("discovery", []),
        ("discovery", {}),
        ("discovery", {"issuer": "https://idp.test/realms/company", "jwks_uri": "https://[broken"}),
        ("discovery", {"issuer": "https://idp.test/realms/company", "jwks_uri": 12}),
        ("discovery", {"issuer": "https://idp.test/realms/company", "jwks_uri": "relative"}),
        ("jwks", {}),
        ("jwks", {"keys": [{"kty": "RSA", "kid": "bad", "n": 123, "e": "AQAB"}]}),
        ("jwks", {"keys": [None]}),
        ("jwks", {"keys": [{"kty": "RSA"}]}),
        ("jwks", {"keys": [{"kty": "RSA", "kid": "bad"}]}),
    ],
)
async def test_malformed_documents(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    endpoint: str,
    document: object,
) -> None:
    """Wrong JSON shapes and incomplete key material are dependency failures."""
    fake_issuer.inject(endpoint, document)
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        with pytest.raises(DependencyUnavailable) as raised:
            await _verifier(http, fake_issuer, clock).verify(fake_issuer.id_token("karl"))
    assert raised.value.context == {"dependency": "company_idp", "reason": "malformed"}


async def test_unsupported_keys_are_filtered_and_algorithm_can_be_absent(
    fake_issuer: FakeCompanyIdp, fake_issuer_transport: httpx.ASGITransport, clock: FakeClock
) -> None:
    """Unsupported keys cannot poison valid RSA material with an inferred algorithm."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        document = (await http.get(fake_issuer.issuer + "/protocol/openid-connect/certs")).json()
        del document["keys"][0]["alg"]
        document["keys"].extend([{"kty": "oct"}, {"kty": "RSA", "alg": "RS512"}, {"kty": []}])
        fake_issuer.inject("jwks", document)
        await _verifier(http, fake_issuer, clock).verify(fake_issuer.id_token("karl"))


@pytest.mark.parametrize(("offset", "accepted"), [(29, True), (30, False)])
async def test_expiration_leeway_boundary(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    clock: FakeClock,
    offset: int,
    accepted: bool,
) -> None:
    """Expiration uses the injected clock with an exclusive leeway boundary."""
    token = fake_issuer.id_token("karl")
    clock.advance(timedelta(seconds=300 + offset))
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        verifier = _verifier(http, fake_issuer, clock)
        if accepted:
            await verifier.verify(token)
        else:
            with pytest.raises(AuthError):
                await verifier.verify(token)


async def test_initial_unknown_key_refresh_is_bounded(
    fake_issuer: FakeCompanyIdp, fake_issuer_transport: httpx.ASGITransport, clock: FakeClock
) -> None:
    """Even a cold cache limits repeated requests with unknown key identifiers."""
    token = fake_issuer.id_token("karl")
    async with httpx.AsyncClient(transport=fake_issuer_transport) as http:
        verifier = _verifier(http, fake_issuer, clock)
        for kid in ["first", "second"]:
            with pytest.raises(AuthError):
                await verifier.verify(_header(token, kid=kid))
        assert fake_issuer.hits["jwks"] == 1
