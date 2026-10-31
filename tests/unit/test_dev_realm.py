"""The development realm, its group directory and the Docker stack agree with the web and API."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
REALM: dict[str, Any] = json.loads((ROOT / "scripts/keycloak/company-realm.json").read_text())
GROUPS: dict[str, list[str]] = yaml.safe_load((ROOT / "scripts/dev-groups.yaml").read_text())
SERVICES: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.app.yml").read_text())["services"]
WEB_ORIGINS = [
    f"http://{host}:{port}" for port in (3000, 5173, 4173) for host in ("localhost", "127.0.0.1")
]


def test_the_web_client_is_confidential_and_uses_the_code_flow_only() -> None:
    web = _client("huron-web")
    assert web["publicClient"] is False
    assert web["clientAuthenticatorType"] == "client-secret"
    assert web["secret"]
    assert web["standardFlowEnabled"] is True
    assert web["implicitFlowEnabled"] is False
    assert web["directAccessGrantsEnabled"] is False
    assert web["serviceAccountsEnabled"] is False
    assert web["attributes"]["oauth2.device.authorization.grant.enabled"] == "false"
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
    assert web["webOrigins"] == []


def test_the_web_client_returns_only_to_the_callback_and_the_signed_out_page() -> None:
    web = _client("huron-web")
    assert sorted(web["redirectUris"]) == sorted(f"{o}/auth/callback" for o in WEB_ORIGINS)
    logout = web["attributes"]["post.logout.redirect.uris"].split("##")
    assert sorted(logout) == sorted(f"{o}/login?status=signed-out" for o in WEB_ORIGINS)


def test_web_id_tokens_carry_the_api_audience_and_access_tokens_do_not() -> None:
    mappers = [
        mapper["config"]
        for mapper in _client("huron-web")["protocolMappers"]
        if mapper["protocolMapper"] == "oidc-audience-mapper"
    ]
    assert mappers == [
        {
            "included.client.audience": "huron-cli",
            "id.token.claim": "true",
            "access.token.claim": "false",
        }
    ]


def test_the_cli_client_allows_the_device_grant_and_any_loopback_port() -> None:
    cli = _client("huron-cli")
    assert cli["publicClient"] is True
    assert cli["attributes"]["oauth2.device.authorization.grant.enabled"] == "true"
    # Keycloak drops the port of an http://127.0.0.1 redirect before it matches this entry.
    assert "http://127.0.0.1/*" in cli["redirectUris"]
    # Keycloak 26 enforces this setting at the device endpoint too, which the CLI does not pass.
    assert "pkce.code.challenge.method" not in cli["attributes"]


@pytest.mark.parametrize(("username", "password"), [("admin", "admin"), ("user", "user")])
def test_the_demo_accounts_have_their_password(username: str, password: str) -> None:
    assert _user(username)["credentials"] == [
        {"type": "password", "value": password, "temporary": False}
    ]


@pytest.mark.parametrize("username", [user["username"] for user in REALM["users"]])
def test_every_realm_user_signs_in_without_a_profile_page(username: str) -> None:
    user = _user(username)
    assert user["enabled"] is True
    assert user["emailVerified"] is True
    assert user["email"] == f"{username}@example.org"
    assert user["firstName"]
    assert user["lastName"]
    assert user["requiredActions"] == []


def test_every_user_of_the_group_directory_is_in_the_realm() -> None:
    assert set(GROUPS) <= {user["username"] for user in REALM["users"]}


def test_admin_is_a_platform_admin_and_user_a_contributor_and_reader() -> None:
    assert GROUPS["admin"] == ["huron-platform-admins"]
    assert sorted(GROUPS["user"]) == ["geo-readers", "helio-contributors"]


def test_the_docker_stack_names_the_issuer_keycloak_stamps_into_tokens() -> None:
    issuer = f"{SERVICES['keycloak']['environment']['KC_HOSTNAME']}/realms/{REALM['realm']}"
    settings = _dev_env()
    assert settings["HURON_COMPANY_ISSUER"] == issuer
    assert SERVICES["web"]["environment"]["HURON_WEB_OIDC_ISSUER"] == issuer
    assert SERVICES["seed"]["environment"]["HURON_SEED_ISSUER"] == issuer
    assert settings["HURON_COMPANY_AUDIENCE"] == "huron-cli"


def test_the_docker_web_uses_the_realm_client() -> None:
    settings = SERVICES["web"]["environment"]
    client = _client(settings["HURON_WEB_OIDC_CLIENT_ID"])
    assert settings["HURON_WEB_OIDC_CLIENT_SECRET"] == client["secret"]
    assert f"{settings['ORIGIN']}/auth/callback" in client["redirectUris"]


def test_the_services_on_the_api_image_never_look_for_it_in_a_registry() -> None:
    policies = {
        name: service.get("pull_policy")
        for name, service in SERVICES.items()
        if name != "api" and service.get("image") == SERVICES["api"]["image"]
    }
    assert policies == {"migrate": "never", "groups": "never"}


def test_the_docker_keycloak_keeps_its_in_memory_realm_while_it_runs() -> None:
    keycloak = SERVICES["keycloak"]
    assert "--db=dev-mem" in keycloak["command"]
    # Without it H2 drops the database once the idle pool has closed its last connection.
    assert keycloak["environment"]["KC_DB_URL_PROPERTIES"] == ";DB_CLOSE_DELAY=-1"


def _client(client_id: str) -> dict[str, Any]:
    (found,) = [client for client in REALM["clients"] if client["clientId"] == client_id]
    return found


def _user(username: str) -> dict[str, Any]:
    (found,) = [user for user in REALM["users"] if user["username"] == username]
    return found


def _dev_env() -> dict[str, str]:
    lines = (ROOT / "dev.env").read_text().splitlines()
    pairs = [line.split("=", 1) for line in lines if line and not line.startswith("#")]
    return {name: value for name, value in pairs}
