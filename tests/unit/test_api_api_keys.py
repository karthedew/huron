"""``POST /api/v1/auth/api-keys``'s response shape and its structural show-once guarantee.

Drives the FastAPI app through a TestClient with an in-memory
an in-memory store set and dev-header auth, ``root`` bootstrapped as
platform owner. Proves the shape of a freshly minted key's response body
and the structural guarantee that ``IssuedApiKey`` can only ever be built
from the minting call's own return value - the idempotency-key
requirement is covered alongside the rest of that header's behavior in
``test_api_rbac.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from huron.applications.api.app import create_app
from huron.applications.api.routes.v1.schema.api_keys import IssuedApiKey
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.security.apikeys import ApiKeyRecord
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A dev-header TestClient over an in-memory repository, with ``root`` as platform owner."""
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


def _headers(subject: str) -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with a fresh idempotency key."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def test_an_issued_api_key_carries_normalized_scopes_and_a_typed_expiry(
    client: TestClient,
) -> None:
    """An issued key's scopes are sorted, with a future expiry and a one-time secret."""
    response = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "laptop", "scopes": ["write", "read"]},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["scopes"] == ["read", "write"]
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)
    assert set(body) == {"id", "name", "scopes", "expires_at", "secret"}


def test_an_issued_api_key_omits_the_project_id_the_request_supplied(client: TestClient) -> None:
    """An issued key's response never echoes back a submitted ``project_id``."""
    response = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "ingest", "project_id": "proj-1"},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    assert "project_id" not in response.json()


# -- the show-once rule is structural, not a convention -----------------


def test_issued_api_key_cannot_be_filled_from_a_stored_record() -> None:
    """Filling ``IssuedApiKey`` from a stored ``ApiKeyRecord`` fails before any field is read.

    ``ApiKeyRecord`` carries ``secret_sha256`` and no plaintext secret - the
    shape a future author might reach for if they forgot the rule. The
    validation fails because the model declares no ``from_attributes``
    config.
    """
    record = ApiKeyRecord(
        key_id="abc123",
        subject="root",
        name="laptop",
        secret_sha256="0" * 64,
        scopes=frozenset({"read"}),
        project_id=None,
        expires_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError) as excinfo:
        IssuedApiKey.model_validate(record)
    (error,) = excinfo.value.errors()
    assert error["type"] == "model_type"
    assert error["loc"] == ()
