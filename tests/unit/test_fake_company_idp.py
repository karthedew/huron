"""Company issuer discovery, signatures, rotation and transport fault contracts."""

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TypedDict
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from starlette.testclient import TestClient

from tests.fakes.ldap_groups import Identities
from tests.fakes.oidc_issuer import Approve, DeviceStep, Endpoint, FakeCompanyIdp, IdpFailure
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
        assert client.get(base + "/inject").status_code == 404
        assert client.get(base + "/auth").status_code == 400
        for suffix in ("token", "auth/device", "revoke"):
            assert client.get(base + "/" + suffix).status_code == 405
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


@pytest.mark.parametrize(
    "endpoint", ["discovery", "jwks", "authorize", "token", "device", "revoke"]
)
@pytest.mark.parametrize("failure", [404, 503, "timeout", "unreachable", "malformed"])
async def test_persistent_faults_clear_and_count_every_request(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
    endpoint: Endpoint,
    failure: IdpFailure,
) -> None:
    """Every injected fault persists until cleared and every attempted request is counted."""
    suffix = {
        "discovery": "/.well-known/openid-configuration",
        "jwks": "/protocol/openid-connect/certs",
        "authorize": "/protocol/openid-connect/auth",
        "token": "/protocol/openid-connect/token",
        "device": "/protocol/openid-connect/auth/device",
        "revoke": "/protocol/openid-connect/revoke",
    }[endpoint]
    method = "GET" if endpoint in ("discovery", "jwks", "authorize") else "POST"
    snapshot = fake_issuer.hits
    with pytest.raises(TypeError):
        snapshot[endpoint] = 99
    fake_issuer.inject(endpoint, failure)
    async with httpx.AsyncClient(transport=fake_issuer_transport) as client:
        for _ in range(2):
            if failure in ("timeout", "unreachable"):
                error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
                with pytest.raises(error, match="injected"):
                    await client.request(method, fake_issuer.issuer + suffix)
            else:
                response = await client.request(method, fake_issuer.issuer + suffix)
                if isinstance(failure, int):
                    assert response.status_code == failure
                    assert response.json() == {"error": "injected"}
                else:
                    assert response.status_code == 200
                    assert response.text == "not json"
        fake_issuer.inject(endpoint, None)
        expected = {"authorize": 400, "token": 401, "device": 401}.get(endpoint, 200)
        assert (await client.request(method, fake_issuer.issuer + suffix)).status_code == expected
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


_VERIFIER = "a" * 43
_CHALLENGE = urlsafe_b64encode(sha256(_VERIFIER.encode()).digest()).rstrip(b"=").decode()
_REDIRECT = "http://127.0.0.1:54831/callback"
_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _url(issuer: FakeCompanyIdp, endpoint: str) -> str:
    return issuer.issuer + "/protocol/openid-connect/" + endpoint


def _authorize_params(issuer: FakeCompanyIdp, **overrides: str) -> dict[str, str]:
    return {
        "client_id": issuer.client_id,
        "redirect_uri": _REDIRECT,
        "response_type": "code",
        "code_challenge": _CHALLENGE,
        "code_challenge_method": "S256",
        "state": "state +/&",
        "scope": "openid profile email",
        **overrides,
    }


def _code(client: TestClient, issuer: FakeCompanyIdp, **overrides: str) -> str:
    response = client.get(
        _url(issuer, "auth"), params=_authorize_params(issuer, **overrides), follow_redirects=False
    )
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["state"] == ["state +/&"]
    assert query["iss"] == [issuer.issuer]
    return query["code"][0]


def _exchange(client: TestClient, issuer: FakeCompanyIdp, **overrides: str) -> httpx.Response:
    return client.post(
        _url(issuer, "token"),
        data={
            "client_id": issuer.client_id,
            "grant_type": "authorization_code",
            "redirect_uri": _REDIRECT,
            "code_verifier": _VERIFIER,
            **overrides,
        },
    )


class _DeviceResponse(TypedDict):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


def _device(client: TestClient, issuer: FakeCompanyIdp) -> _DeviceResponse:
    response = client.post(
        _url(issuer, "auth/device"),
        data={
            "client_id": issuer.client_id,
            "scope": "openid email",
            "code_challenge": _CHALLENGE,
            "code_challenge_method": "S256",
        },
    )
    assert response.status_code == 200
    return response.json()


def _verified(client: TestClient, issuer: FakeCompanyIdp, token: str) -> dict[str, object]:
    keys = client.get(_url(issuer, "certs")).json()["keys"]
    key = next(key for key in keys if key["kid"] == jwt.get_unverified_header(token)["kid"])
    return jwt.decode(
        token,
        jwt.PyJWK(key),
        algorithms=[key["alg"]],
        audience=issuer.client_id,
        issuer=issuer.issuer,
        options={"verify_exp": False, "verify_iat": False},
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_id": "foreign"},
        {"client_id": ""},
        {"redirect_uri": ""},
        {"redirect_uri": "https://evil.test/callback"},
        {"redirect_uri": "http://localhost:1234/callback"},
        {"redirect_uri": "https://127.0.0.1:1234/callback"},
        {"redirect_uri": "http://127.0.0.1/callback"},
        {"redirect_uri": "http://127.0.0.1:1234"},
        {"redirect_uri": "http://127.0.0.1:0/callback"},
        {"redirect_uri": "http://127.0.0.1:99999/callback"},
        {"redirect_uri": "http://127.0.0.1:abc/callback"},
        {"redirect_uri": "http://user@127.0.0.1:1234/callback"},
        {"redirect_uri": "http://127.0.0.1:1234/callback#fragment"},
        {"redirect_uri": "http://[broken/callback"},
        {"redirect_uri": "\nhttp://127.0.0.1:1234/callback"},
        {"redirect_uri": "http://127.0.0.1:1234/call\tback"},
    ],
)
def test_authorize_refuses_untrusted_callbacks(
    fake_issuer: FakeCompanyIdp,
    overrides: dict[str, str],
) -> None:
    """Foreign clients and non-loopback callbacks never receive a redirect."""
    with TestClient(fake_issuer.app, follow_redirects=False) as client:
        response = client.get(
            _url(fake_issuer, "auth"), params=_authorize_params(fake_issuer, **overrides)
        )
    assert response.status_code == 400
    assert "location" not in response.headers


@pytest.mark.parametrize(
    "challenge,method", [("", "S256"), (_CHALLENGE, "plain"), (_CHALLENGE, "")]
)
def test_pkce_required_on_authorize_and_device(
    fake_issuer: FakeCompanyIdp,
    challenge: str,
    method: str,
) -> None:
    """Both authorization entry points require a challenge and the S256 method."""
    params = _authorize_params(fake_issuer, code_challenge=challenge, code_challenge_method=method)
    with TestClient(fake_issuer.app, follow_redirects=False) as client:
        response = client.get(_url(fake_issuer, "auth"), params=params)
        assert response.status_code == 302
        query = parse_qs(urlsplit(response.headers["location"]).query)
        assert query == {
            "error": ["invalid_request"],
            "state": [params["state"]],
            "iss": [fake_issuer.issuer],
        }
        response = client.post(_url(fake_issuer, "auth/device"), data=params)
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_request"}


def test_authorize_denial_and_clear_with_existing_query(fake_issuer: FakeCompanyIdp) -> None:
    """Denials echo state and clearing the control restores code issuance."""
    with TestClient(fake_issuer.app, follow_redirects=False) as client:
        fake_issuer.deny_authorize("access_denied")
        params = _authorize_params(fake_issuer, redirect_uri=_REDIRECT + "?original=yes")
        response = client.get(_url(fake_issuer, "auth"), params=params)
        assert response.status_code == 302
        assert parse_qs(urlsplit(response.headers["location"]).query) == {
            "original": ["yes"],
            "state": [params["state"]],
            "iss": [fake_issuer.issuer],
            "error": ["access_denied"],
        }
        fake_issuer.deny_authorize(None)
        assert _code(client, fake_issuer)


@pytest.mark.parametrize("nonce", [None, "nonce +/&", ""])
def test_code_identity_nonce_rotation_and_reuse(
    fake_issuer: FakeCompanyIdp,
    identities: Identities,
    clock: FakeClock,
    nonce: str | None,
) -> None:
    """Code grants bind the user and nonce; rotation omits nonce and reuse kills the family."""
    assert fake_issuer.login_as == "karl"
    fake_issuer.login_as = "sam"
    with TestClient(fake_issuer.app) as client:
        code = _code(client, fake_issuer, **({"nonce": nonce} if nonce is not None else {}))
        fake_issuer.login_as = "rita"
        response = _exchange(client, fake_issuer, code=code)
        assert response.status_code == 200
        tokens = response.json()
        assert set(tokens) == {
            "access_token",
            "token_type",
            "expires_in",
            "refresh_token",
            "id_token",
            "scope",
        }
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 300
        assert tokens["scope"] == "openid profile email"
        body = _verified(client, fake_issuer, tokens["id_token"])
        assert body["sub"] == identities.user("sam").id
        assert body["preferred_username"] == "sam"
        assert body["organization"] == identities.organization and "groups" not in body
        if nonce is None:
            assert "nonce" not in body
        else:
            assert body["nonce"] == nonce
        assert _exchange(client, fake_issuer, code=code).json() == {"error": "invalid_grant"}
        clock.advance(timedelta(seconds=1))
        rotated = _exchange(
            client, fake_issuer, grant_type="refresh_token", refresh_token=tokens["refresh_token"]
        ).json()
        assert rotated["refresh_token"] != tokens["refresh_token"]
        assert rotated["access_token"] != tokens["access_token"]
        assert rotated["id_token"] != tokens["id_token"]
        assert rotated["scope"] == tokens["scope"]
        refreshed = _verified(client, fake_issuer, rotated["id_token"])
        assert "nonce" not in refreshed and refreshed["sub"] == body["sub"]
        for token in (tokens["refresh_token"], rotated["refresh_token"], "unknown"):
            response = _exchange(
                client, fake_issuer, grant_type="refresh_token", refresh_token=token
            )
            assert response.status_code == 400 and response.json() == {"error": "invalid_grant"}


@pytest.mark.parametrize(
    "changes",
    [
        {"code_verifier": "wrong"},
        {"code_verifier": ""},
        {"redirect_uri": _REDIRECT + "/other"},
        {"code": "unknown"},
    ],
)
def test_code_binding_refusals(fake_issuer: FakeCompanyIdp, changes: dict[str, str]) -> None:
    """Unknown codes, wrong callbacks and invalid proof keys cannot redeem a code."""
    with TestClient(fake_issuer.app) as client:
        response = _exchange(client, fake_issuer, **{"code": _code(client, fake_issuer), **changes})
        assert response.status_code == 400 and response.json() == {"error": "invalid_grant"}


@pytest.mark.parametrize("elapsed,expected", [(59, 200), (60, 400), (61, 400)])
def test_code_expiry_uses_injected_clock(
    fake_issuer: FakeCompanyIdp,
    clock: FakeClock,
    elapsed: int,
    expected: int,
) -> None:
    """Authorization codes expire exactly sixty seconds after issue."""
    with TestClient(fake_issuer.app) as client:
        code = _code(client, fake_issuer)
        clock.advance(timedelta(seconds=elapsed))
        response = _exchange(client, fake_issuer, code=code)
        assert response.status_code == expected
        if expected == 400:
            assert response.json() == {"error": "invalid_grant"}


@pytest.mark.parametrize(
    "grant_type", ["authorization_code", "refresh_token", _DEVICE_GRANT, "unknown"]
)
def test_token_client_is_checked_before_grant(
    fake_issuer: FakeCompanyIdp,
    grant_type: str,
) -> None:
    """Every token grant refuses foreign clients before considering the grant."""
    with TestClient(fake_issuer.app) as client:
        response = _exchange(client, fake_issuer, client_id="foreign", grant_type=grant_type)
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        response = client.post(_url(fake_issuer, "auth/device"), data={"client_id": "foreign"})
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        response = _exchange(client, fake_issuer, grant_type="unknown")
        assert response.status_code == 400 and response.json() == {
            "error": "unsupported_grant_type"
        }


def test_device_timing_approval_and_consumption(
    fake_issuer: FakeCompanyIdp,
    clock: FakeClock,
    identities: Identities,
) -> None:
    """Polling grows the interval by five seconds and consumes approved grants only once."""
    with TestClient(fake_issuer.app) as client:
        device = _device(client, fake_issuer)
        assert device["interval"] == 5 and device["expires_in"] == 600
        assert device["verification_uri"] == fake_issuer.issuer + "/device"
        assert parse_qs(urlsplit(device["verification_uri_complete"]).query) == {
            "user_code": [device["user_code"]]
        }
        assert len(device["user_code"]) == 9 and device["user_code"][4] == "-"
        form = {"grant_type": _DEVICE_GRANT, "device_code": device["device_code"]}
        for seconds, error in [
            (0, "authorization_pending"),
            (4, "slow_down"),
            (9, "slow_down"),
            (14, "slow_down"),
            (20, "authorization_pending"),
        ]:
            clock.advance(timedelta(seconds=seconds))
            assert _exchange(client, fake_issuer, **form).json() == {"error": error}
        fake_issuer.approve(device["user_code"], "rita")
        clock.advance(timedelta(seconds=20))
        response = _exchange(client, fake_issuer, **form)
        assert response.status_code == 200
        tokens = response.json()
        assert tokens["scope"] == "openid email"
        body = _verified(client, fake_issuer, tokens["id_token"])
        assert body["sub"] == identities.user("rita").id and "nonce" not in body
        assert _exchange(client, fake_issuer, **form).json() == {"error": "invalid_grant"}
        assert _exchange(
            client, fake_issuer, grant_type=_DEVICE_GRANT, device_code="unknown"
        ).json() == {"error": "invalid_grant"}


@pytest.mark.parametrize("terminal", ["access_denied", "expired_token"])
def test_device_script_order_and_terminal_state(
    fake_issuer: FakeCompanyIdp,
    clock: FakeClock,
    terminal: DeviceStep,
) -> None:
    """Queued responses take precedence; denial and expiry persist after the script ends."""
    with TestClient(fake_issuer.app) as client:
        device = _device(client, fake_issuer)
        fake_issuer.script_device("authorization_pending", "slow_down", terminal)
        for expected in ("authorization_pending", "slow_down", terminal, terminal):
            response = _exchange(
                client, fake_issuer, grant_type=_DEVICE_GRANT, device_code=device["device_code"]
            )
            assert response.status_code == 400 and response.json() == {"error": expected}
        clock.advance(timedelta(seconds=600))
        assert _exchange(
            client, fake_issuer, grant_type=_DEVICE_GRANT, device_code=device["device_code"]
        ).json() == {"error": "expired_token"}


def test_scripted_approval_still_requires_pkce(
    fake_issuer: FakeCompanyIdp, clock: FakeClock
) -> None:
    """A scripted approval cannot bypass the grant's proof key."""
    with TestClient(fake_issuer.app) as client:
        device = _device(client, fake_issuer)
        fake_issuer.script_device(Approve("sam"))
        form = {"grant_type": _DEVICE_GRANT, "device_code": device["device_code"]}
        assert _exchange(client, fake_issuer, **form, code_verifier="wrong").json() == {
            "error": "invalid_grant"
        }
        clock.advance(timedelta(seconds=5))
        response = _exchange(client, fake_issuer, **form)
        assert response.status_code == 200
        assert (
            _verified(client, fake_issuer, response.json()["id_token"])["preferred_username"]
            == "sam"
        )


def test_device_custom_lifetime_interval_and_expiry(
    identities: Identities, clock: FakeClock
) -> None:
    """Configured device lifetime and interval are enforced at their exact boundaries."""
    issuer = FakeCompanyIdp(identities, clock, device_ttl=timedelta(seconds=8), interval=3)
    with TestClient(issuer.app) as client:
        device = _device(client, issuer)
        assert device["expires_in"] == 8 and device["interval"] == 3
        form = {"grant_type": _DEVICE_GRANT, "device_code": device["device_code"]}
        assert _exchange(client, issuer, **form).json() == {"error": "authorization_pending"}
        clock.advance(timedelta(seconds=3))
        assert _exchange(client, issuer, **form).json() == {"error": "authorization_pending"}
        issuer.approve(device["user_code"], "karl")
        clock.advance(timedelta(seconds=5))
        assert _exchange(client, issuer, **form).json() == {"error": "expired_token"}


def test_controls_validate_people_and_codes_atomically(fake_issuer: FakeCompanyIdp) -> None:
    """Invalid user controls raise without changing login or queuing partial scripts."""
    with pytest.raises(KeyError):
        fake_issuer.login_as = "unknown"
    assert fake_issuer.login_as == "karl"
    with pytest.raises(KeyError):
        fake_issuer.approve("unknown", "karl")
    with TestClient(fake_issuer.app) as client:
        device = _device(client, fake_issuer)
        with pytest.raises(KeyError):
            fake_issuer.approve(device["user_code"], "unknown")
        with pytest.raises(KeyError):
            fake_issuer.script_device("access_denied", Approve("unknown"))
        assert _exchange(
            client, fake_issuer, grant_type=_DEVICE_GRANT, device_code=device["device_code"]
        ).json() == {"error": "authorization_pending"}


@pytest.mark.parametrize("revoke_previous", [False, True])
def test_revocation_records_tokens_and_revokes_family(
    fake_issuer: FakeCompanyIdp,
    revoke_previous: bool,
) -> None:
    """Revoking any known family member invalidates its current refresh token."""
    with TestClient(fake_issuer.app) as client:
        original = _exchange(client, fake_issuer, code=_code(client, fake_issuer)).json()
        rotated = _exchange(
            client, fake_issuer, grant_type="refresh_token", refresh_token=original["refresh_token"]
        ).json()
        token = original["refresh_token"] if revoke_previous else rotated["refresh_token"]
        snapshot = fake_issuer.revoked
        for value in ("unknown", "", token, token):
            response = client.post(
                _url(fake_issuer, "revoke"), data={"client_id": "foreign", "token": value}
            )
            assert response.status_code == 200
        assert snapshot == ()
        assert fake_issuer.revoked == ("unknown", "", token, token)
        assert _exchange(
            client, fake_issuer, grant_type="refresh_token", refresh_token=rotated["refresh_token"]
        ).json() == {"error": "invalid_grant"}
        other = _exchange(client, fake_issuer, code=_code(client, fake_issuer)).json()
        assert (
            _exchange(
                client,
                fake_issuer,
                grant_type="refresh_token",
                refresh_token=other["refresh_token"],
            ).status_code
            == 200
        )


async def test_sync_authorization_async_redemption_share_single_use_state(
    fake_issuer: FakeCompanyIdp,
    fake_issuer_transport: httpx.ASGITransport,
) -> None:
    """A code created on a TestClient thread is consumed once across both transports."""
    with TestClient(fake_issuer.app) as client:
        code = _code(client, fake_issuer, nonce="cross-transport")
        async with httpx.AsyncClient(transport=fake_issuer_transport) as async_client:
            response = await async_client.post(
                _url(fake_issuer, "token"),
                data={
                    "client_id": fake_issuer.client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _REDIRECT,
                    "code_verifier": _VERIFIER,
                },
            )
        assert response.status_code == 200
        assert (
            _verified(client, fake_issuer, response.json()["id_token"])["nonce"]
            == "cross-transport"
        )
        assert _exchange(client, fake_issuer, code=code).json() == {"error": "invalid_grant"}


@pytest.mark.parametrize("grant_type", ["authorization_code", "refresh_token", _DEVICE_GRANT])
def test_foreign_client_cannot_consume_live_grants(
    fake_issuer: FakeCompanyIdp, grant_type: str
) -> None:
    """A foreign client's refusal leaves the configured client's live grant usable."""
    with TestClient(fake_issuer.app) as client:
        if grant_type == "authorization_code":
            form = {"code": _code(client, fake_issuer)}
        elif grant_type == "refresh_token":
            tokens = _exchange(client, fake_issuer, code=_code(client, fake_issuer)).json()
            form = {"refresh_token": tokens["refresh_token"]}
        else:
            device = _device(client, fake_issuer)
            fake_issuer.approve(device["user_code"], "karl")
            form = {"device_code": device["device_code"]}
        response = _exchange(
            client, fake_issuer, grant_type=grant_type, client_id="foreign", **form
        )
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        assert _exchange(client, fake_issuer, grant_type=grant_type, **form).status_code == 200


def test_simultaneous_code_redemptions_have_one_winner(fake_issuer: FakeCompanyIdp) -> None:
    """Concurrent transport threads cannot redeem the same authorization code twice."""
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(fake_issuer.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        code = _code(client, fake_issuer)
        futures = [pool.submit(_exchange, client, fake_issuer, code=code) for _ in range(2)]
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert next(response for response in responses if response.status_code == 400).json() == {
        "error": "invalid_grant"
    }
