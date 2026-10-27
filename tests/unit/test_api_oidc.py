"""Legacy bearer authentication through the production company verifier."""

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings
from tests.unit.support import memory_stores

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("audience", [None, "another-client"])
def test_company_bearer_issues_a_key_for_the_company_username(
    tmp_path, fake_issuer, fake_issuer_transport, clock, audience
) -> None:
    """Signed company identity names the key owner by username rather than opaque subject."""
    stores = memory_stores()
    app = create_app(
        settings=ApiSettings(
            env="production",
            auth_mode="oidc",
            data_root=str(tmp_path / "data"),
            database_url="postgresql://unused",
            classification_vocabulary=[
                ClassificationValue(code="open", order=0, discoverable=True)
            ],
            oidc=OidcSettings(
                issuer=fake_issuer.issuer, client_id=fake_issuer.client_id, audience=audience
            ),
        ),
        stores=stores,
        company_idp_transport=fake_issuer_transport,
        clock=clock,
    )
    claims = {"aud": audience, "azp": audience} if audience else {}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "laptop"},
            headers={
                "Authorization": "Bearer " + fake_issuer.id_token("karl", claims=claims),
                "Idempotency-Key": "issue-key",
            },
        )
    assert response.status_code == 201, response.text
    assert stores.api_keys.records[response.json()["id"]].subject == "karl"
    assert stores.principals.records == {}


@pytest.mark.parametrize("failure", ["forged", "unreachable", "invalid_username"])
def test_company_bearer_refusals_keep_authentication_and_dependency_errors_distinct(
    tmp_path, fake_issuer, fake_issuer_transport, clock, failure
) -> None:
    """Invalid credentials challenge the caller; failed discovery requests a later retry."""
    token = fake_issuer.id_token(
        "karl",
        forged=failure == "forged",
        claims={"preferred_username": "bad/name"} if failure == "invalid_username" else {},
    )
    if failure == "unreachable":
        fake_issuer.rotate_key()
        token = fake_issuer.id_token("karl")
        fake_issuer.inject("discovery", "unreachable")
    app = create_app(
        settings=ApiSettings(
            env="production",
            auth_mode="oidc",
            data_root=str(tmp_path / "data"),
            database_url="postgresql://unused",
            classification_vocabulary=[
                ClassificationValue(code="open", order=0, discoverable=True)
            ],
            oidc=OidcSettings(issuer=fake_issuer.issuer, client_id=fake_issuer.client_id),
        ),
        stores=memory_stores(),
        company_idp_transport=fake_issuer_transport,
        clock=clock,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/organizations", headers={"Authorization": "Bearer " + token})
    if failure == "unreachable":
        assert response.status_code == 503
        assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
        assert response.headers["Retry-After"] == "30"
    else:
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIAL"
        assert response.headers["WWW-Authenticate"] == "Bearer"
