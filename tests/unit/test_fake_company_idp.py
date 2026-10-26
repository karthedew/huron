"""Company issuer discovery, signatures, rotation and transport fault contracts."""

from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from starlette.testclient import TestClient

from tests.fakes.ldap_groups import Identities
from tests.fakes.oidc_issuer import Endpoint, FakeCompanyIdp, IdpFailure
from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit


def test_discovery_and_custom_issuer_path(identities: Identities, clock: FakeClock) -> None:
    """Discovery describes the exact public-client protocol under the issuer path."""
    issuer = FakeCompanyIdp(
        identities, clock, issuer="https://other.test/nested/realm", client_id="custom"
    )
    assert issuer.issuer == "https://other.test/nested/realm"
    assert issuer.client_id == "custom"
    assert issuer.app is issuer.app
    with pytest.raises(AttributeError):
        issuer.issuer = "changed"
    with pytest.raises(AttributeError):
        issuer.client_id = "changed"
    base = issuer.issuer + "/protocol/openid-connect"
    with TestClient(issuer.app) as client:
        response = client.get(issuer.issuer + "/.well-known/openid-configuration")
        assert response.status_code == 200
        assert response.json() == {
            "issuer": issuer.issuer,
            "authorization_endpoint": base + "/auth",
            "token_endpoint": base + "/token",
            "device_authorization_endpoint": base + "/auth/device",
            "revocation_endpoint": base + "/revoke",
            "jwks_uri": base + "/certs",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
                "urn:ietf:params:oauth:grant-type:device_code",
            ],
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256", "ES256"],
            "subject_types_supported": ["public"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
        assert client.get("/.well-known/openid-configuration").status_code == 404
        assert client.post(issuer.issuer + "/.well-known/openid-configuration").status_code == 405
        for suffix in ("auth", "token", "auth/device", "revoke", "inject"):
            assert client.get(base + "/" + suffix).status_code == 404
        keys = client.get(base + "/certs").json()["keys"]
        token = issuer.id_token("karl")
        assert (
            jwt.decode(
                token,
                jwt.PyJWK(keys[0]),
                algorithms=["RS256"],
                audience="custom",
                issuer=issuer.issuer,
                options={"verify_exp": False, "verify_iat": False},
            )["aud"]
            == "custom"
        )


def test_revocation_can_be_omitted(identities: Identities, clock: FakeClock) -> None:
    """An issuer without revocation support omits that discovery member."""
    issuer = FakeCompanyIdp(identities, clock, revocation=False)
    with TestClient(issuer.app) as client:
        assert (
            "revocation_endpoint"
            not in client.get(issuer.issuer + "/.well-known/openid-configuration").json()
        )


@pytest.mark.parametrize("username", ["karl", "sam", "rita"])
async def test_signed_claims_and_public_keys(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    identities: Identities,
    clock: FakeClock,
    username: str,
) -> None:
    """Every fixture identity verifies against public-only served RSA key material."""
    async with httpx.AsyncClient(transport=fake_issuer_transport) as client:
        response = await client.get(fake_issuer.issuer + "/protocol/openid-connect/certs")
    (key,) = response.json()["keys"]
    assert set(key) == {"kid", "kty", "alg", "use", "n", "e", "key_ops"}
    assert key["kid"] == "fake-rs256-1"
    assert key["use"] == "sig"
    token = fake_issuer.id_token(username)
    body = jwt.decode(
        token,
        jwt.PyJWK(key),
        algorithms=["RS256"],
        audience="huron-cli",
        issuer=fake_issuer.issuer,
        options={"verify_exp": False, "verify_iat": False},
    )
    user = identities.user(username)
    now = int(clock.now().timestamp())
    assert body == {
        "iss": fake_issuer.issuer,
        "sub": user.id,
        "aud": "huron-cli",
        "azp": "huron-cli",
        "iat": now,
        "auth_time": now,
        "exp": now + 300,
        "preferred_username": username,
        "name": f"{user.given_name} {user.family_name}",
        "given_name": user.given_name,
        "family_name": user.family_name,
        "email": user.email,
        "email_verified": True,
        "organization": identities.organization,
        "sid": f"session-{user.id}",
        "typ": "ID",
    }
    assert fake_issuer.hits["jwks"] == 1


def test_overrides_drops_clock_and_unknown_identity(identities: Identities) -> None:
    """Overrides permit invalid-token cases while timestamps follow only the injected clock."""
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))
    issuer = FakeCompanyIdp(identities, clock, token_ttl=timedelta(seconds=17))
    token = issuer.id_token(
        "karl",
        claims={"aud": "other", "groups": ["injected"], "nonce": "n"},
        drop=("email", "nonce", "absent"),
    )
    body = jwt.decode(token, options={"verify_signature": False})
    assert body["iat"] == 1893456000
    assert body["auth_time"] == body["iat"]
    assert body["exp"] == body["iat"] + 17
    assert body["aud"] == "other"
    assert body["groups"] == ["injected"]
    assert "email" not in body and "nonce" not in body
    clock.advance(timedelta(seconds=23))
    assert (
        jwt.decode(issuer.id_token("sam"), options={"verify_signature": False})["iat"] == 1893456023
    )
    with pytest.raises(KeyError):
        issuer.id_token("missing")
    with pytest.raises(KeyError):
        issuer.id_token("karl", kid="missing")


def test_rotation_retirement_and_forged_signatures(fake_issuer: FakeCompanyIdp) -> None:
    """RSA and EC keys verify selected tokens; forged and retired signatures cannot verify."""
    with TestClient(fake_issuer.app) as client:
        url = fake_issuer.issuer + "/protocol/openid-connect/certs"
        for kid in ("fake-rs256-1", fake_issuer.rotate_key()):
            keys = {key["kid"]: key for key in client.get(url).json()["keys"]}
            key = keys[kid]
            assert not {"d", "p", "q", "dp", "dq", "qi"} & key.keys()
            token = fake_issuer.id_token("karl", kid=kid)
            assert jwt.get_unverified_header(token)["kid"] == kid
            jwt.decode(
                token,
                jwt.PyJWK(key),
                algorithms=[key["alg"]],
                audience="huron-cli",
                options={"verify_exp": False, "verify_iat": False},
            )
            with pytest.raises(jwt.InvalidSignatureError):
                jwt.decode(
                    fake_issuer.id_token("karl", kid=kid, forged=True),
                    jwt.PyJWK(key),
                    algorithms=[key["alg"]],
                    audience="huron-cli",
                    options={"verify_exp": False, "verify_iat": False},
                )
        assert set(keys) == {"fake-rs256-1", "fake-es256-1"}
        assert set(keys["fake-es256-1"]) == {"kid", "kty", "alg", "use", "crv", "x", "y"}
        assert keys["fake-es256-1"]["crv"] == "P-256"
        assert fake_issuer.rotate_key(retire_previous=True) == "fake-es256-2"
        assert {key["kid"] for key in client.get(url).json()["keys"]} == {
            "fake-rs256-1",
            "fake-es256-2",
        }
        assert jwt.get_unverified_header(fake_issuer.id_token("karl"))["kid"] == "fake-es256-2"
        with pytest.raises(KeyError):
            fake_issuer.id_token("karl", kid="fake-es256-1")


def test_default_key_is_shared_but_state_is_isolated(
    identities: Identities, clock: FakeClock
) -> None:
    """Instances reuse the process RSA key without sharing rotations or request counts."""
    first, second = FakeCompanyIdp(identities, clock), FakeCompanyIdp(identities, clock)
    with TestClient(first.app) as one, TestClient(second.app) as two:
        path = first.issuer + "/protocol/openid-connect/certs"
        assert one.get(path).json() == two.get(path).json()
        first.rotate_key(retire_previous=True)
        assert two.get(path).json()["keys"][0]["kid"] == "fake-rs256-1"
    assert first.hits["jwks"] == 1
    assert second.hits["jwks"] == 2


@pytest.mark.parametrize("endpoint", ["discovery", "jwks"])
@pytest.mark.parametrize("failure", [404, 503, "timeout", "unreachable", "malformed"])
async def test_persistent_faults_clear_and_count_every_request(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    endpoint: Endpoint,
    failure: IdpFailure,
) -> None:
    """Every injected fault persists until cleared and every attempted request is counted."""
    suffix = (
        "/.well-known/openid-configuration"
        if endpoint == "discovery"
        else "/protocol/openid-connect/certs"
    )
    snapshot = fake_issuer.hits
    with pytest.raises(TypeError):
        snapshot[endpoint] = 99
    fake_issuer.inject(endpoint, failure)
    async with httpx.AsyncClient(transport=fake_issuer_transport) as client:
        for _ in range(2):
            if failure in ("timeout", "unreachable"):
                error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
                with pytest.raises(error, match="injected"):
                    await client.get(fake_issuer.issuer + suffix)
            else:
                response = await client.get(fake_issuer.issuer + suffix)
                if isinstance(failure, int):
                    assert response.status_code == failure
                    assert response.json() == {"error": "injected"}
                else:
                    assert response.status_code == 200
                    assert response.text == "not json"
        fake_issuer.inject(endpoint, None)
        assert (await client.get(fake_issuer.issuer + suffix)).status_code == 200
        fake_issuer.inject(endpoint, None)
    assert snapshot[endpoint] == 0
    assert fake_issuer.hits[endpoint] == 3
    assert sum(fake_issuer.hits.values()) == 3


def test_issuer_mismatch_only_changes_discovery(fake_issuer: FakeCompanyIdp) -> None:
    """Issuer mismatch preserves endpoint URLs and is refused on other endpoints."""
    fake_issuer.inject("discovery", "issuer_mismatch")
    with TestClient(fake_issuer.app) as client:
        document = client.get(fake_issuer.issuer + "/.well-known/openid-configuration").json()
        assert document["issuer"] == fake_issuer.issuer + "/other"
        assert document["jwks_uri"] == fake_issuer.issuer + "/protocol/openid-connect/certs"
        fake_issuer.inject("discovery", None)
        assert (
            client.get(fake_issuer.issuer + "/.well-known/openid-configuration").json()["issuer"]
            == fake_issuer.issuer
        )
    for endpoint in ("jwks", "authorize", "token", "device", "revoke"):
        with pytest.raises(ValueError, match="only to discovery"):
            fake_issuer.inject(endpoint, "issuer_mismatch")


async def test_sync_and_async_clients_share_counted_state(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
) -> None:
    """Threaded and async HTTP callers observe one issuer and count every request."""
    from concurrent.futures import ThreadPoolExecutor

    url = fake_issuer.issuer + "/protocol/openid-connect/certs"
    with TestClient(fake_issuer.app) as sync_client, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(sync_client.get, url) for _ in range(8)]
        async with httpx.AsyncClient(transport=fake_issuer_transport) as async_client:
            for _ in range(8):
                assert (await async_client.get(url)).status_code == 200
        assert all(future.result().status_code == 200 for future in futures)
    assert fake_issuer.hits["jwks"] == 16
