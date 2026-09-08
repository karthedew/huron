"""``If-Match`` parsing, and the 412/422 split it drives on a PATCH route.

``expected_version`` turns a header into the integer version a client
believes is current; a header that never named a version is a schema
violation (422), and only a well-formed header naming the wrong version
reaches the 412 comparison against the stored record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.routes.v1.preconditions import expected_version
from huron.applications.api.settings import ApiSettings, ClassificationValue
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


def _headers() -> dict[str, str]:
    """Dev-header credentials for ``root``."""
    return {"X-Huron-Subject": "root"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A dev-header TestClient with ``root`` as platform owner."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        yield client


@pytest.mark.parametrize(
    ("if_match", "version"),
    [
        pytest.param('"3"', 3, id="strong-entity-tag"),
        pytest.param('W/"3"', 3, id="weak-entity-tag"),
        pytest.param('"0"', 0, id="strong-entity-tag-zero"),
        pytest.param("3", 3, id="bare-integer"),
        pytest.param("0", 0, id="bare-integer-zero"),
    ],
)
def test_expected_version_reads_the_version_a_well_formed_header_names(
    if_match: str, version: int
) -> None:
    """A header naming a version, quoted or bare, parses to that integer."""
    assert expected_version(if_match) == version


@pytest.mark.parametrize(
    "if_match",
    [
        pytest.param("3W", id="trailing-garbage"),
        pytest.param("//3", id="leading-garbage"),
        pytest.param("abc", id="not-a-number"),
        pytest.param("", id="empty"),
        pytest.param('"3', id="unterminated-quote"),
        pytest.param('3"', id="only-closing-quote"),
        pytest.param("W/3", id="weak-prefix-without-quotes"),
        pytest.param("-3", id="negative"),
        pytest.param('""', id="quoted-empty"),
        pytest.param("9" * 5000, id="absurdly-long-digit-run"),
    ],
)
def test_expected_version_refuses_a_header_that_names_no_version(if_match: str) -> None:
    """A header that is not ``"N"``, ``W/"N"`` or a bare integer is a schema violation."""
    with pytest.raises(RequestValidationError):
        expected_version(if_match)


def test_patching_with_a_well_formed_header_naming_the_wrong_version_is_a_precondition_failure(
    client: TestClient,
) -> None:
    """A syntactically valid ``If-Match`` naming a stale version 412s, never 422."""
    created = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers={**_headers(), "Idempotency-Key": "create-astro"},
    )
    assert created.status_code == 201, created.text
    organization_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/organizations/{organization_id}",
        json={"title": "Renamed"},
        headers={**_headers(), "If-Match": '"5"'},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "PRECONDITION_FAILED"


def test_patching_with_an_unparseable_header_is_a_request_validation_failure(
    client: TestClient,
) -> None:
    """A header that never named a version 422s as ``REQUEST_INVALID``, never 412."""
    created = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers={**_headers(), "Idempotency-Key": "create-astro"},
    )
    assert created.status_code == 201, created.text
    organization_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/organizations/{organization_id}",
        json={"title": "Renamed"},
        headers={**_headers(), "If-Match": "garbage"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_patching_with_an_absurdly_long_digit_run_is_a_request_validation_failure(
    client: TestClient,
) -> None:
    """A digit run too long for any real version number 422s, never 500s."""
    created = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers={**_headers(), "Idempotency-Key": "create-astro"},
    )
    assert created.status_code == 201, created.text
    organization_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/organizations/{organization_id}",
        json={"title": "Renamed"},
        headers={**_headers(), "If-Match": '"' + "9" * 5000 + '"'},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"
