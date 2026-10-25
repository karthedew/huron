"""OIDC bearer verification and provider discovery contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient, Response
from jwt.algorithms import RSAAlgorithm

from huron.core.foundation.errors import AuthError
from huron.core.security.oidc import (
    JwksVerifier,
    OidcClient,
    OidcProviderConfig,
    OidcResolver,
)

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"
CLIENT_ID = "huron-web"
KID = "test-signing-key"


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


def _id_token(
    private_key: RSAPrivateKey,
    *,
    kid: str = KID,
    signing_key: RSAPrivateKey | None = None,
    **overrides: object,
) -> str:
    """Build a signed ID token from a default valid claim set, overridable by keyword.

    ``exp``/``iat`` are relative to the real clock because PyJWT checks
    expiry against wall-clock time with no injectable override.
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


# -- OidcClient discovery ------------------------------------------------


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
            )
    assert client.provider == OidcProviderConfig(
        issuer=ISSUER,
        authorization_endpoint=f"{ISSUER}/authorize",
        token_endpoint=f"{ISSUER}/token",
        jwks_uri=f"{ISSUER}/jwks",
        end_session_endpoint=f"{ISSUER}/logout",
    )


async def test_discover_raises_when_the_issuer_rejects_the_request() -> None:
    """A discovery request the issuer answers with an error status raises AuthError."""
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=Response(500))
        async with AsyncClient() as http:
            with pytest.raises(AuthError):
                await OidcClient.discover(
                    http,
                    ISSUER,
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
                )
