"""OIDC bearer verification and the pending-login cookie, proved against fakes and a mocked IdP.

LoginFlow's signed encoding, JwksVerifier's rejection cases, and
OidcClient's discovery and authorization-code exchange are all exercised
against a respx-mocked IdP. PyJWT fetches a JWKS over plain ``urllib``
rather than ``httpx``, so respx cannot see that call. The ``serve_jwks``
fixture stands in for it by patching ``PyJWKClient.fetch_data`` to return
a JWKS built from an in-test RSA keypair - the same seam respx occupies
for the httpx calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient, Response
from jwt.algorithms import RSAAlgorithm

from huron.pkg.auth.errors import AuthError
from huron.pkg.auth.oidc import (
    JwksVerifier,
    LoginFlow,
    OidcClient,
    OidcProviderConfig,
    OidcResolver,
    code_challenge_s256,
)

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"
CLIENT_ID = "huron-web"
KID = "test-signing-key"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="session")
def private_key() -> RSAPrivateKey:
    """An RSA-2048 keypair generated once and reused for the whole test session."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks_document(private_key: RSAPrivateKey) -> dict[str, object]:
    """The JWKS document publishing ``private_key``'s public half under ``KID``."""
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = KID
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return {"keys": [jwk]}


@pytest.fixture
def serve_jwks(monkeypatch: pytest.MonkeyPatch, jwks_document: dict[str, object]) -> None:
    """``PyJWKClient`` fetches ``jwks_document`` in place of a real JWKS HTTP call."""
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: jwks_document)


@pytest.fixture
def provider() -> OidcProviderConfig:
    """The discovery endpoints of a fake identity provider at ``ISSUER``."""
    return OidcProviderConfig(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/authorize",
        token_endpoint=f"{ISSUER}/token",
        jwks_uri=f"{ISSUER}/jwks",
        end_session_endpoint=f"{ISSUER}/logout",
    )


def _id_token(
    private_key: RSAPrivateKey,
    *,
    kid: str = KID,
    signing_key: RSAPrivateKey | None = None,
    **overrides: object,
) -> str:
    """Build a signed ID token from a default valid claim set, overridable by keyword.

    ``exp``/``iat`` are relative to the real clock (not the fixed ``T0``
    used for LoginFlow) because PyJWT checks expiry against wall-clock
    time with no injectable override.
    """
    issued = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "user-123",
        "aud": CLIENT_ID,
        "exp": int((issued + timedelta(minutes=5)).timestamp()),
        "iat": int(issued.timestamp()),
        "nonce": "expected-nonce",
        "name": "Ada Lovelace",
        "email": "ada@example.org",
        "groups": ["physics", "admins"],
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key or private_key, algorithm="RS256", headers={"kid": kid})


def _expired_overrides() -> dict[str, object]:
    """Claim overrides producing an ID token whose ``exp`` has already passed."""
    now = datetime.now(UTC)
    return {
        "exp": int((now - timedelta(minutes=1)).timestamp()),
        "iat": int((now - timedelta(minutes=10)).timestamp()),
    }


# -- OidcResolver (bearer tokens, verifier injected) ----------------------


async def test_oidc_resolver_maps_claims_to_a_principal() -> None:
    """A verified token's ``sub`` and groups claims become the principal's subject and groups."""
    resolver = OidcResolver(lambda _token: {"sub": "alice", "groups": ["physics"]})
    principal = await resolver.resolve("some-bearer-token")
    assert principal.subject == "alice"
    assert principal.groups == frozenset({"physics"})
    assert principal.authentication_method == "oidc"


async def test_oidc_resolver_rejects_claims_missing_a_string_subject() -> None:
    """A token whose claims carry no string ``sub`` is refused with AuthError."""
    resolver = OidcResolver(lambda _token: {"groups": ["physics"]})
    with pytest.raises(AuthError):
        await resolver.resolve("some-bearer-token")


# -- JwksVerifier --------------------------------------------------------


def test_jwks_verifier_returns_claims_for_a_validly_signed_token(
    private_key: RSAPrivateKey, serve_jwks: None
) -> None:
    """A token signed by the key the JWKS publishes verifies and yields its claims."""
    verifier = JwksVerifier(issuer=ISSUER, audience=CLIENT_ID, jwks_url=f"{ISSUER}/jwks")
    claims = verifier(_id_token(private_key))
    assert claims["sub"] == "user-123"


def test_jwks_verifier_rejects_a_token_whose_kid_is_not_in_the_jwks(
    private_key: RSAPrivateKey, serve_jwks: None
) -> None:
    """A token naming a ``kid`` absent from the JWKS is rejected."""
    verifier = JwksVerifier(issuer=ISSUER, audience=CLIENT_ID, jwks_url=f"{ISSUER}/jwks")
    with pytest.raises(AuthError):
        verifier(_id_token(private_key, kid="some-other-key"))


def test_jwks_verifier_rejects_a_token_signed_by_a_different_key(serve_jwks: None) -> None:
    """A token claiming the legitimate ``kid`` but signed with a different key is rejected."""
    impostor_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = JwksVerifier(issuer=ISSUER, audience=CLIENT_ID, jwks_url=f"{ISSUER}/jwks")
    with pytest.raises(AuthError):
        verifier(_id_token(impostor_key, signing_key=impostor_key))


def test_jwks_verifier_rejects_an_expired_token(
    private_key: RSAPrivateKey, serve_jwks: None
) -> None:
    """A token whose ``exp`` has already passed is rejected."""
    verifier = JwksVerifier(issuer=ISSUER, audience=CLIENT_ID, jwks_url=f"{ISSUER}/jwks")
    expired = _id_token(private_key, **_expired_overrides())
    with pytest.raises(AuthError):
        verifier(expired)


def test_jwks_verifier_rejects_the_wrong_audience(
    private_key: RSAPrivateKey, serve_jwks: None
) -> None:
    """A token issued for a different audience (``aud``) is rejected."""
    verifier = JwksVerifier(issuer=ISSUER, audience=CLIENT_ID, jwks_url=f"{ISSUER}/jwks")
    with pytest.raises(AuthError):
        verifier(_id_token(private_key, aud="someone-else"))


# -- OidcClient: discovery and the authorization URL ----------------------


async def test_authorization_url_carries_pkce_and_the_oidc_parameters(
    provider: OidcProviderConfig,
) -> None:
    """The authorization URL carries the client id, redirect URI, state, nonce and PKCE."""
    async with AsyncClient() as http:
        client = OidcClient(
            http,
            provider,
            client_id=CLIENT_ID,
            client_secret="shh",
            redirect_url="https://app.example/callback",
        )
        url = client.authorization_url(state="s1", nonce="n1", code_challenge="c1")

    split = urlsplit(url)
    query = parse_qs(split.query)
    assert f"{split.scheme}://{split.netloc}{split.path}" == provider.authorization_endpoint
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == ["https://app.example/callback"]
    assert query["state"] == ["s1"]
    assert query["nonce"] == ["n1"]
    assert query["code_challenge"] == ["c1"]
    assert query["code_challenge_method"] == ["S256"]


async def test_discover_builds_a_client_from_the_well_known_document() -> None:
    """``discover`` builds a working client from the provider's well-known document."""
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                    "end_session_endpoint": f"{ISSUER}/logout",
                },
            )
        )
        async with AsyncClient() as http:
            client = await OidcClient.discover(
                http,
                ISSUER,
                client_id=CLIENT_ID,
                client_secret="shh",
                redirect_url="https://app.example/callback",
            )
    url = client.authorization_url(state="s", nonce="n", code_challenge="c")
    assert url.startswith(f"{ISSUER}/authorize?")


async def test_discover_raises_when_the_issuer_rejects_the_request() -> None:
    """A discovery request the issuer answers with an error status raises AuthError."""
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=Response(500))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await OidcClient.discover(
                    http,
                    ISSUER,
                    client_id=CLIENT_ID,
                    client_secret="shh",
                    redirect_url="https://app.example/callback",
                )


_COMPLETE_DISCOVERY_DOCUMENT: dict[str, object] = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "end_session_endpoint": f"{ISSUER}/logout",
}


@pytest.mark.parametrize(
    "missing_field", ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"]
)
async def test_discover_raises_when_the_document_is_missing_a_required_field(
    missing_field: str,
) -> None:
    """A discovery document missing any of the four required fields raises AuthError naming it."""
    document = {
        field: value
        for field, value in _COMPLETE_DISCOVERY_DOCUMENT.items()
        if field != missing_field
    }
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=Response(200, json=document)
        )
        async with AsyncClient() as http:
            with pytest.raises(AuthError, match=missing_field):
                await OidcClient.discover(
                    http,
                    ISSUER,
                    client_id=CLIENT_ID,
                    client_secret="shh",
                    redirect_url="https://app.example/callback",
                )


async def test_discover_raises_when_the_document_issuer_does_not_match() -> None:
    """A discovery document whose ``issuer`` differs from the requested issuer raises AuthError."""
    document = {**_COMPLETE_DISCOVERY_DOCUMENT, "issuer": "https://impostor.example"}
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            return_value=Response(200, json=document)
        )
        async with AsyncClient() as http:
            with pytest.raises(AuthError, match=ISSUER):
                await OidcClient.discover(
                    http,
                    ISSUER,
                    client_id=CLIENT_ID,
                    client_secret="shh",
                    redirect_url="https://app.example/callback",
                )


# -- OidcClient.exchange_code ----------------------------------------------


def _client(provider: OidcProviderConfig, http: AsyncClient) -> OidcClient:
    """An ``OidcClient`` configured for the fake provider with fixed test credentials."""
    return OidcClient(
        http,
        provider,
        client_id=CLIENT_ID,
        client_secret="shh",
        redirect_url="https://app.example/callback",
    )


def _mock_token_endpoint(id_token: str) -> respx.Route:
    """The mocked token endpoint answers with the given ID token as ``id_token``."""
    return respx.post(f"{ISSUER}/token").mock(
        return_value=Response(200, json={"id_token": id_token})
    )


async def test_exchange_code_maps_claims_to_an_oidc_user(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """A successful code exchange maps the ID token's claims onto the returned OidcUser."""
    with respx.mock:
        _mock_token_endpoint(_id_token(private_key))
        async with AsyncClient() as http:
            user = await _client(provider, http).exchange_code(
                code="auth-code", code_verifier="verifier", nonce="expected-nonce"
            )
    assert user.idp_subject == "user-123"
    assert user.display_name == "Ada Lovelace"
    assert user.email == "ada@example.org"
    assert user.groups == frozenset({"physics", "admins"})


async def test_exchange_code_falls_back_to_subject_when_optional_claims_are_absent(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """Absent name, email and groups claims fall back to the subject, None and an empty set."""
    token = _id_token(private_key, name=None, email=None, groups=None)
    with respx.mock:
        _mock_token_endpoint(token)
        async with AsyncClient() as http:
            user = await _client(provider, http).exchange_code(
                code="auth-code", code_verifier="verifier", nonce="expected-nonce"
            )
    assert user.display_name == "user-123"
    assert user.email is None
    assert user.groups == frozenset()


async def test_exchange_code_posts_grant_type_code_and_pkce_to_the_token_endpoint(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """The token request posts grant_type, code, redirect_uri, client_secret and the verifier.

    The outgoing token request must actually carry what a confidential
    client + PKCE exchange requires - respx records the real request rather
    than trusting the mocked response alone.
    """
    with respx.mock:
        route = _mock_token_endpoint(_id_token(private_key))
        async with AsyncClient() as http:
            await _client(provider, http).exchange_code(
                code="the-auth-code", code_verifier="the-code-verifier", nonce="expected-nonce"
            )
    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent["grant_type"] == ["authorization_code"]
    assert sent["code"] == ["the-auth-code"]
    assert sent["redirect_uri"] == ["https://app.example/callback"]
    assert sent["client_secret"] == ["shh"]
    assert sent["code_verifier"] == ["the-code-verifier"]


async def test_exchange_code_rejects_a_mismatched_nonce(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """A code exchange whose nonce does not match the ID token's nonce claim is rejected."""
    with respx.mock:
        _mock_token_endpoint(_id_token(private_key))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="a-different-nonce"
                )


async def test_exchange_code_rejects_the_wrong_audience(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """A code exchange returning an ID token issued for the wrong audience is rejected."""
    with respx.mock:
        _mock_token_endpoint(_id_token(private_key, aud="someone-else"))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="expected-nonce"
                )


async def test_exchange_code_rejects_an_expired_token(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """A code exchange returning an already-expired ID token is rejected."""
    expired = _id_token(private_key, **_expired_overrides())
    with respx.mock:
        _mock_token_endpoint(expired)
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="expected-nonce"
                )


async def test_exchange_code_rejects_a_subject_claim_that_is_not_a_string(
    private_key: RSAPrivateKey, provider: OidcProviderConfig, serve_jwks: None
) -> None:
    """A code exchange whose ID token has a non-string ``sub`` claim is rejected."""
    with respx.mock:
        _mock_token_endpoint(_id_token(private_key, sub=12345))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="expected-nonce"
                )


async def test_exchange_code_raises_when_the_token_endpoint_rejects_the_request(
    provider: OidcProviderConfig,
) -> None:
    """A token endpoint that answers the exchange with an error status raises AuthError."""
    with respx.mock:
        respx.post(f"{ISSUER}/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="expected-nonce"
                )


async def test_exchange_code_raises_when_the_token_response_has_no_id_token(
    provider: OidcProviderConfig,
) -> None:
    """A token response with no ``id_token`` field raises AuthError."""
    with respx.mock:
        respx.post(f"{ISSUER}/token").mock(return_value=Response(200, json={"access_token": "at"}))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await _client(provider, http).exchange_code(
                    code="auth-code", code_verifier="verifier", nonce="expected-nonce"
                )


def test_map_claims_rejects_a_subject_claim_type_that_pyjwt_would_never_pass_through(
    provider: OidcProviderConfig,
) -> None:
    """``_map_claims`` rejects a non-string ``sub`` claim even when called directly.

    ``_map_claims`` guards its own contract independently of JwksVerifier
    - which already refuses a non-string ``sub`` before this ever runs.
    """
    client = OidcClient(
        AsyncClient(),
        provider,
        client_id=CLIENT_ID,
        client_secret="shh",
        redirect_url="https://app.example/callback",
    )
    with pytest.raises(AuthError):
        client._map_claims({"sub": 12345})


# -- PKCE -------------------------------------------------------------------


def test_code_challenge_s256_matches_the_rfc7636_worked_example() -> None:
    """``code_challenge_s256`` matches the RFC 7636 worked example's expected challenge."""
    # RFC 7636 Appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


# -- LoginFlow ---------------------------------------------------------------

SECRET = b"cookie-signing-secret"


def test_login_flow_encode_then_decode_round_trips() -> None:
    """A ``LoginFlow`` decodes back to the exact flow that was encoded."""
    flow = LoginFlow.new(return_to="/dashboard", now=T0)
    encoded = flow.encode(SECRET)
    decoded = LoginFlow.decode(encoded, SECRET, now=T0 + timedelta(seconds=5))
    assert decoded == flow


def test_login_flow_decode_rejects_a_signature_made_with_a_different_secret() -> None:
    """Decoding a flow cookie with the wrong signing secret is rejected."""
    flow = LoginFlow.new(now=T0)
    encoded = flow.encode(SECRET)
    with pytest.raises(AuthError):
        LoginFlow.decode(encoded, b"a-different-secret", now=T0)


def test_login_flow_decode_rejects_a_flow_older_than_max_age() -> None:
    """A flow older than ``max_age`` seconds is refused as expired."""
    flow = LoginFlow.new(now=T0)
    encoded = flow.encode(SECRET)
    with pytest.raises(AuthError):
        LoginFlow.decode(encoded, SECRET, now=T0 + timedelta(seconds=601))


def test_login_flow_decode_accepts_a_flow_at_the_edge_of_max_age() -> None:
    """A flow exactly ``max_age`` seconds old still decodes successfully."""
    flow = LoginFlow.new(now=T0)
    encoded = flow.encode(SECRET)
    assert LoginFlow.decode(encoded, SECRET, now=T0 + timedelta(seconds=600)) == flow


def test_login_flow_decode_rejects_invalid_base64() -> None:
    """A cookie value that is not valid base64 raises AuthError, not a decoding error."""
    with pytest.raises(AuthError):
        LoginFlow.decode("not valid base64!!", SECRET, now=T0)


def test_login_flow_decode_rejects_a_payload_too_short_to_carry_a_signature() -> None:
    """A payload too short to hold a signature is rejected."""
    encoded = base64.urlsafe_b64encode(b"too-short").decode()
    with pytest.raises(AuthError):
        LoginFlow.decode(encoded, SECRET, now=T0)


def test_login_flow_decode_rejects_a_correctly_sized_payload_missing_the_dot_separator() -> None:
    """A payload long enough for a signature but missing the dot separator is rejected."""
    # Long enough to carry a signature, but the byte where the separating
    # "." belongs is something else entirely.
    raw = b"x" * 40
    encoded = base64.urlsafe_b64encode(raw).decode()
    with pytest.raises(AuthError):
        LoginFlow.decode(encoded, SECRET, now=T0)


def test_login_flow_decode_rejects_a_signed_payload_that_is_not_valid_json() -> None:
    """A correctly signed payload that is not valid JSON is rejected."""
    payload = b"not-json"
    signature = hmac.new(SECRET, payload, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(payload + b"." + signature).decode()
    with pytest.raises(AuthError):
        LoginFlow.decode(encoded, SECRET, now=T0)


@pytest.mark.parametrize("return_to", ["evil.example", "//evil.example"])
def test_login_flow_new_refuses_a_return_to_that_is_not_a_local_path(return_to: str) -> None:
    """``LoginFlow.new`` refuses a ``return_to`` that is not a local path."""
    with pytest.raises(AuthError):
        LoginFlow.new(return_to=return_to, now=T0)
