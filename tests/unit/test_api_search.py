"""``GET /api/v1/search`` access control, ahead of the projection it will search.

The route is closed to anonymous callers like the rest of the versioned
surface, and still answers ``503`` for an authenticated caller until the
search projection exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue
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


def test_search_refuses_an_anonymous_caller(tmp_path: Path) -> None:
    """An anonymous caller is refused 401 with the INVALID_CREDENTIAL problem code."""
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get("/api/v1/search")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "INVALID_CREDENTIAL"


def test_search_is_unavailable_to_an_authenticated_caller_until_the_projection_ships(
    tmp_path: Path,
) -> None:
    """An authenticated caller gets 503 with PROJECTION_UNAVAILABLE until the projection exists."""
    with TestClient(create_app(settings=_settings(tmp_path), stores=memory_stores())) as client:
        response = client.get("/api/v1/search", headers={"X-Huron-Subject": "root"})
    assert response.status_code == 503
    assert response.json()["code"] == "PROJECTION_UNAVAILABLE"


def test_search_advertises_no_response_body_in_its_openapi_document(tmp_path: Path) -> None:
    """The OpenAPI document declares an empty response schema for the search route's 200."""
    app = create_app(settings=_settings(tmp_path), stores=memory_stores())
    operation = app.openapi()["paths"]["/api/v1/search"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {}
