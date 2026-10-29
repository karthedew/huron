"""Company token verification, the group directory and the exchange."""

from datetime import timedelta

import httpx
import jwt
import pytest

from huron.core.security.broker import (
    CompanyTokenVerifier,
    GroupDirectoryUnavailable,
    HttpGroupDirectory,
    KeyRing,
    TokenExchange,
    TokenInvalid,
    TokenIssuer,
    TokenVerifier,
    generate_key,
)
from huron.pkg.errors import Unavailable
from tests.fakes.groups import FakeGroups, groups_transport
from tests.fakes.issuer import AUDIENCE, ISSUER, FakeIssuer
from tests.support.clock import START, frozen

NOW = START.timestamp()


@pytest.fixture
def issuer() -> FakeIssuer:
    return FakeIssuer()


def verifier_for(issuer: FakeIssuer, clock=None) -> CompanyTokenVerifier:  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=issuer.transport())
    return CompanyTokenVerifier(http, ISSUER, AUDIENCE, clock or frozen())


async def test_valid_company_tokens_yield_the_identity(issuer: FakeIssuer) -> None:
    verifier = verifier_for(issuer)
    identity = await verifier.verify(issuer.sign("dave", now=NOW))
    assert (identity.subject, identity.username, identity.display_name) == (
        "sub-dave",
        "dave",
        "Dave",
    )
    await verifier.verify(issuer.sign("erin", now=NOW))
    discovery_fetches = [url for url in issuer.requests if url.endswith("configuration")]
    assert len(discovery_fetches) == 1


async def test_username_falls_back_to_the_subject(issuer: FakeIssuer) -> None:
    token = issuer.sign("x", now=NOW, preferred_username=None, name=None)
    identity = await verifier_for(issuer).verify(token)
    assert identity.username == "sub-x"
    assert identity.display_name == "sub-x"


@pytest.mark.parametrize("case", ["expired", "audience", "issuer", "garbage", "hs256", "kid"])
async def test_bad_company_tokens_are_refused(issuer: FakeIssuer, case: str) -> None:
    tokens = {
        "expired": lambda: issuer.sign("d", now=NOW - 1000, expires_in=60),
        "audience": lambda: issuer.sign("d", now=NOW, audience="other"),
        "issuer": lambda: issuer.sign("d", now=NOW, iss="https://evil"),
        "garbage": lambda: "nope",
        "hs256": lambda: jwt.encode({"sub": "x"}, "k" * 32, "HS256"),
        "kid": lambda: FakeIssuer(kid="other").sign("d", now=NOW),
    }
    with pytest.raises(TokenInvalid):
        await verifier_for(issuer).verify(tokens[case]())


async def test_unknown_kid_refreshes_at_most_once_a_minute(issuer: FakeIssuer) -> None:
    clock = frozen()
    verifier = verifier_for(issuer, clock)
    stranger = FakeIssuer(kid="rotated").sign("d", now=NOW)
    for _ in range(3):
        with pytest.raises(TokenInvalid):
            await verifier.verify(stranger)
    jwks_fetches = [url for url in issuer.requests if url.endswith("/certs")]
    assert len(jwks_fetches) == 1
    clock.advance(timedelta(minutes=2))
    with pytest.raises(TokenInvalid):
        await verifier.verify(stranger)
    assert len([url for url in issuer.requests if url.endswith("/certs")]) == 2


async def test_an_unreachable_provider_is_unavailable(issuer: FakeIssuer) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    verifier = CompanyTokenVerifier(http, ISSUER, AUDIENCE, frozen())
    with pytest.raises(Unavailable):
        await verifier.verify(issuer.sign("d", now=NOW))


async def test_http_group_directory_reads_groups_and_treats_404_as_none() -> None:
    http = httpx.AsyncClient(transport=groups_transport({"dave": ["a", "b"]}))
    directory = HttpGroupDirectory(http, "http://groups.test/")
    assert await directory.groups_for("dave") == {"a", "b"}
    assert await directory.groups_for("nobody") == frozenset()


@pytest.mark.parametrize(
    "transport",
    [
        groups_transport({}, status=503),
        httpx.MockTransport(lambda r: httpx.Response(200, text="not json")),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"groups": "a"})),
        httpx.MockTransport(lambda r: httpx.Response(200, json=[])),
    ],
)
async def test_http_group_directory_failures_are_unavailable(
    transport: httpx.MockTransport,
) -> None:
    directory = HttpGroupDirectory(httpx.AsyncClient(transport=transport), "http://groups.test")
    with pytest.raises(GroupDirectoryUnavailable) as raised:
        await directory.groups_for("dave")
    assert raised.value.status == 503


async def test_unreachable_group_directory_is_unavailable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    directory = HttpGroupDirectory(
        httpx.AsyncClient(transport=httpx.MockTransport(fail)), "http://g"
    )
    with pytest.raises(GroupDirectoryUnavailable):
        await directory.groups_for("dave")


async def test_exchange_issues_a_huron_token_with_the_directory_groups(
    issuer: FakeIssuer,
) -> None:
    clock = frozen()
    ring = KeyRing([generate_key(clock)], timedelta(hours=1), clock)
    huron = TokenIssuer(ring, clock, "https://huron.test", "huron", timedelta(hours=8))
    exchange = TokenExchange(
        verifier_for(issuer, clock), FakeGroups({"dave": ["helio-contributors"]}), huron
    )
    result = await exchange.exchange(issuer.sign("dave", now=NOW))
    assert result.claims.groups == ("helio-contributors",)
    verified = TokenVerifier(ring, "https://huron.test", "huron", clock).verify(result.token)
    assert verified.sub == "dave"


async def test_exchange_fails_without_a_token_when_groups_are_unavailable(
    issuer: FakeIssuer,
) -> None:
    clock = frozen()
    ring = KeyRing([generate_key(clock)], timedelta(hours=1), clock)
    huron = TokenIssuer(ring, clock, "i", "a", timedelta(hours=1))
    directory = HttpGroupDirectory(
        httpx.AsyncClient(transport=groups_transport({}, status=503)), "http://g"
    )
    exchange = TokenExchange(verifier_for(issuer, clock), directory, huron)
    with pytest.raises(GroupDirectoryUnavailable):
        await exchange.exchange(issuer.sign("dave", now=NOW))
