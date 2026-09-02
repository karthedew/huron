"""``GET /api/v1/search``: closed to anonymous callers like the rest of the
versioned surface, and still ``503`` for an authenticated one until the
search projection exists."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )


def test_search_refuses_an_anonymous_caller(tmp_path: Path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        response = client.get("/api/v1/search")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "INVALID_CREDENTIAL"


def test_search_is_unavailable_to_an_authenticated_caller_until_the_projection_ships(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        response = client.get("/api/v1/search", headers={"X-Huron-Subject": "root"})
    assert response.status_code == 503
    assert response.json()["code"] == "PROJECTION_UNAVAILABLE"


def test_search_advertises_no_response_body_in_its_openapi_document(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path))
    operation = app.openapi()["paths"]["/api/v1/search"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {}
