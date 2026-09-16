"""``GET /api/v1/roles`` access control and its fidelity to the role registry.

The route serves the role catalog and is closed to anonymous callers -
the whole platform's capability model is not something an unauthenticated
caller needs to enumerate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.security.roles import ROLES
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path) -> ApiSettings:
    """A development ``ApiSettings`` with dev-headers auth and one open classification value."""
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )


def test_roles_refuses_an_anonymous_caller(tmp_path: Path) -> None:
    """An anonymous caller is refused 401 with the INVALID_CREDENTIAL problem code."""
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get("/api/v1/roles")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "INVALID_CREDENTIAL"


def test_roles_lists_the_catalog_for_any_authenticated_caller(tmp_path: Path) -> None:
    """Any authenticated caller receives 200 with a role catalog that includes platform_owner."""
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get("/api/v1/roles", headers={"X-Huron-Subject": "anyone"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    codes = {item["code"] for item in body}
    assert "platform_owner" in codes


def test_roles_are_a_pure_function_of_the_role_registry(tmp_path: Path) -> None:
    """Each role view reproduces its ROLES entry field by field, with set-like fields sorted."""
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get("/api/v1/roles", headers={"X-Huron-Subject": "anyone"})
    body = response.json()

    assert [item["code"] for item in body] == list(ROLES.keys())
    for item, role in zip(body, ROLES.values(), strict=True):
        assert item["title"] == role.title
        assert item["description"] == role.description
        assert item["capabilities"] == sorted(role.capabilities)
        assert item["bindable_scopes"] == sorted(scope.value for scope in role.bindable_scopes)
        assert item["allowed_principal_kinds"] == sorted(role.allowed_principal_kinds)
        assert [grant["capability"] for grant in item["layer_grants"]] == [
            grant.capability for grant in role.layer_grants
        ]
        for grant_view, grant in zip(item["layer_grants"], role.layer_grants, strict=True):
            expected = sorted(grant.layers) if grant.layers is not None else None
            assert grant_view["layers"] == expected
