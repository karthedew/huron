"""Raw web transport proves exact authority and real immutable publication."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.raw import ingest
from tests.raw_web_client import SECRET, RawWebClient
from tests.raw_web_support import raw_web_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def raw(tmp_path: Path) -> Iterator[RawWebClient]:
    """Bind the real Raw workflow to memory persistence and temporary POSIX storage."""
    settings = ApiSettings(
        env="development",
        auth_mode="credentials",
        data_root=str(tmp_path),
        database_url="postgresql://unused",
        raw_bridge_secret=SECRET,
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        completion_reserve_bytes=0,
    )
    with TestClient(create_app(settings=settings, stores=raw_web_stores())) as client:
        yield RawWebClient(client)


def test_upload_commit_registration_retry_and_immutable_download(
    raw: RawWebClient, tmp_path: Path
) -> None:
    """Retries retain one revision; manifests, range reads and registration use real storage."""
    session = raw.create()
    assert raw.create()["id"] == session["id"]
    heartbeat = raw.request("POST", f"/api/raw-web/uploads/{session['id']}/heartbeat")
    assert heartbeat.status_code == 200
    receipt = raw.finish(session)
    assert receipt["registration"]["state"] == "pending"
    assert receipt["committed_by"] == raw.actor
    prefix = f"/api/raw-web/uploads/{session['id']}"
    status = raw.request("GET", prefix).json()
    assert status["state"] == "COMMITTED"
    assert status["registration"]["state"] == "pending"
    acknowledged = raw.request(
        "POST", prefix + "/registration", body={"revision_id": receipt["id"]}
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "registered"
    assert (
        raw.request("POST", prefix + "/registration", body={"revision_id": receipt["id"]}).json()
        == acknowledged.json()
    )
    replay = raw.request(
        "POST",
        prefix + "/commit",
        body={
            "manifest_sha256": session["manifest_sha256"],
            "metadata": {"title": "Observed source", "creators": ["NASA scientist"]},
        },
        headers={"if-match": '"0"', "idempotency-key": f"commit-{session['id']}"},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == receipt["id"]
    assert replay.json()["registration"]["state"] == "registered"
    record = raw.request("GET", f"/api/raw-web/revisions/{receipt['id']}")
    assert record.status_code == 200
    manifest = raw.request("GET", f"/api/raw-web/revisions/{receipt['id']}/manifest")
    assert (
        manifest.json()["files"][0]["sha256"] == hashlib.sha256(b"real uploaded bytes").hexdigest()
    )
    download = raw.request(
        "GET", f"/api/raw-web/revisions/{receipt['id']}/files/payload/science%20data.csv"
    )
    assert download.status_code == 200, download.text
    assert download.content == b"real uploaded bytes"
    page = raw.request("GET", f"/api/raw-web/datasets/{session['dataset_id']}/revisions").json()
    assert len(page["revisions"]) == 1 and page["next_before"] is None
    assert len(list(tmp_path.rglob("COMMITTED"))) == 1
    second = raw.create(b"new independent bytes", key="upload-two")
    raw.finish(second, b"new independent bytes")
    assert (
        raw.request(
            "GET", f"/api/raw-web/datasets/{session['dataset_id']}/revisions?before=2"
        ).json()["revisions"][0]["id"]
        == receipt["id"]
    )
    assert download.content == b"real uploaded bytes"


def test_multipart_completion_uses_actual_checksums(
    raw: RawWebClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple parts assemble into verified independent bytes before publication."""
    monkeypatch.setattr(ingest, "PART_BYTES", 4)
    session = raw.create(b"three-parts")
    assert session["part_bytes"] == 4 and session["files"][0]["part_count"] == 3
    receipt = raw.finish(session, b"three-parts")
    assert receipt["total_bytes"] == 11


def test_wrong_actor_target_and_revoked_authority_cannot_drive_upload(raw: RawWebClient) -> None:
    """Signed caller inputs cannot swap persisted targets or bypass session ownership."""
    session = raw.create()
    path = f"/api/raw-web/uploads/{session['id']}"
    actor = raw.actor
    raw.actor = f"huron-web:{uuid4()}"
    assert raw.request("GET", path).status_code == 404
    raw.actor = actor
    raw.target = {**raw.target, "catalog": "another-catalog"}
    assert raw.request("GET", path).status_code == 404
    raw.target = session["target"]
    raw.permissions = ["read"]
    assert raw.request("POST", path + "/verify").status_code == 403
    raw.permissions = []
    assert raw.request("GET", path).status_code == 403


def test_incomplete_transfer_and_request_hash_mismatch_never_commit(raw: RawWebClient) -> None:
    """Incomplete and altered transfers leave no publication or successful part ledger."""
    session = raw.create()
    prefix = f"/api/raw-web/uploads/{session['id']}"
    part = f"{prefix}/files/{session['files'][0]['file_id']}/parts/1"
    mismatch = raw.request(
        "PUT", part, data=b"real uploaded bytes", claims={"body_sha256": "0" * 64}
    )
    assert mismatch.status_code == 401, mismatch.text
    ledger = raw.request("GET", prefix).json()
    assert ledger["files"][0]["completed_parts"] == []
    assert raw.request("POST", prefix + "/verify").status_code == 400
    assert (
        raw.request(
            "POST", prefix + "/registration", body={"revision_id": session["revision_id"]}
        ).status_code
        == 403
    )
    receipt = raw.finish(session)
    assert receipt["number"] == 1


def test_create_permission_and_valid_manifest_precede_internal_provisioning(
    raw: RawWebClient,
) -> None:
    """New targets require explicit creation authority and complete valid manifest paths."""
    body = {
        "title": "Test",
        "files": [{"path": "payload/test", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    }
    raw.permissions = ["read", "write"]
    assert (
        raw.request(
            "POST", "/api/raw-web/uploads", body=body, headers={"idempotency-key": "new"}
        ).status_code
        == 403
    )
    raw.permissions.append("create")
    body["files"][0]["path"] = "payload/../escape"
    assert (
        raw.request(
            "POST", "/api/raw-web/uploads", body=body, headers={"idempotency-key": "bad"}
        ).status_code
        == 400
    )


def test_abort_releases_the_target_without_publishing(raw: RawWebClient) -> None:
    """An owned abort releases the one-active-upload lock and leaves no revision."""
    session = raw.create()
    result = raw.request("POST", f"/api/raw-web/uploads/{session['id']}/abort")
    assert result.status_code == 200 and result.json()["state"] == "ABORTED"
    assert raw.create(key="another-upload")["revision_number"] == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"method": "DELETE"},
        {"path": "/api/raw-web/wrong"},
        {"body_sha256": "0" * 64},
        {"headers": {"if-match": '"9"'}},
        {"sub": "admin"},
        {"aud": "other-service"},
        {"iat": 1, "exp": 2},
        {"permissions": ["admin"]},
    ],
)
def test_request_binding_rejects_modified_claims(
    raw: RawWebClient, claims: dict[str, object]
) -> None:
    """A valid signature does not excuse wrong audience, identity, expiry or request binding."""
    result = raw.request("GET", f"/api/raw-web/uploads/{uuid4()}", claims=claims)
    assert result.status_code == 401, result.text


def test_credentials_mode_never_accepts_development_subject_headers(raw: RawWebClient) -> None:
    """The new bridge deployment mode cannot authenticate arbitrary development headers."""
    assert (
        raw.client.get("/api/v1/organizations", headers={"x-huron-subject": "root"}).status_code
        == 401
    )
    assert raw.request("GET", "/api/v1/organizations").status_code == 401
    assert raw.client.get(f"/api/raw-web/uploads/{uuid4()}").status_code == 401


def test_delegation_requires_signature_lifetime_and_strong_configuration(raw: RawWebClient) -> None:
    """Only short-lived signed bridge requests can supply actor identity."""
    import time

    from pydantic import ValidationError

    from huron.core.security.authentication_errors import AuthError
    from huron.core.security.raw_delegation import RawDelegationVerifier

    with pytest.raises(ValueError, match="32 bytes"):
        RawDelegationVerifier("short")
    with pytest.raises(ValidationError, match="32 bytes"):
        ApiSettings(
            env="development",
            auth_mode="credentials",
            database_url="unused",
            classification_vocabulary=[
                ClassificationValue(code="open", order=0, discoverable=True)
            ],
            raw_bridge_secret="short",
        )
    with pytest.raises(AuthError):
        RawDelegationVerifier(SECRET).verify("invalid.jwt", method="GET", path="/", headers={})
    now = int(time.time())
    result = raw.request(
        "GET", f"/api/raw-web/uploads/{uuid4()}", claims={"iat": now, "exp": now + 61}
    )
    assert result.status_code == 401


def test_bridge_disabled_is_undiscoverable(tmp_path: Path) -> None:
    """Installing the route does not enable trusted delegation without a configured secret."""
    settings = ApiSettings(
        env="development",
        auth_mode="credentials",
        data_root=str(tmp_path),
        database_url="unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    with TestClient(create_app(settings=settings, stores=raw_web_stores())) as client:
        assert (
            RawWebClient(client).request("GET", f"/api/raw-web/uploads/{uuid4()}").status_code
            == 404
        )


async def test_delegated_bindings_never_grant_service_account_authority() -> None:
    """Human delegation cannot synthesize privileged service-account capabilities."""
    from huron.core.foundation.errors import ResourceNotFound
    from huron.core.security.raw_delegation import DelegatedBindings

    with pytest.raises(ResourceNotFound):
        await DelegatedBindings(()).service_account_by_subject("admin")


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "untrusted-web"},
        {"permissions": {"read": True}},
        {
            "target": {
                "endpoint": "http://polaris.test",
                "realm": "POLARIS",
                "catalog": "test",
                "namespace": [""],
                "name": "test",
            }
        },
        {
            "target": {
                "endpoint": "http://polaris.test",
                "realm": "POLARIS",
                "catalog": "test",
                "namespace": ["x" * 257],
                "name": "test",
            }
        },
    ],
)
def test_delegation_shape_and_issuer_fail_closed(
    raw: RawWebClient, claims: dict[str, object]
) -> None:
    """Strict claims reject alternate issuer, capability objects and invalid target shapes."""
    assert raw.request("GET", f"/api/raw-web/uploads/{uuid4()}", claims=claims).status_code == 401


def test_signed_retry_headers_and_encoded_query_are_request_bound(raw: RawWebClient) -> None:
    """Changing retry identity or an encoded path/query invalidates an otherwise signed request."""
    body = {"title": "Test", "files": []}
    changed_header = raw.request(
        "POST",
        "/api/raw-web/uploads",
        body=body,
        headers={"idempotency-key": "actual"},
        claims={"headers": {"idempotency-key": "different"}},
    )
    assert changed_header.status_code == 401
    bad_json = raw.request(
        "POST",
        "/api/raw-web/uploads",
        body=body,
        headers={"idempotency-key": "actual"},
        claims={"body_sha256": "f" * 64},
    )
    assert bad_json.status_code == 401
    dataset = uuid4()
    changed_query = raw.request(
        "GET",
        f"/api/raw-web/datasets/{dataset}/revisions?before=2",
        claims={"path": f"/api/raw-web/datasets/{dataset}/revisions?before=1"},
    )
    assert changed_query.status_code == 401
    changed_encoding = raw.request(
        "GET",
        f"/api/raw-web/revisions/{uuid4()}/files/payload/a%20b",
        claims={"path": "/api/raw-web/revisions/unknown/files/payload/a b"},
    )
    assert changed_encoding.status_code == 401


def test_revision_access_requires_current_exact_target_but_not_upload_ownership(
    raw: RawWebClient,
) -> None:
    """Other catalog readers can read committed data; cross-target references stay concealed."""
    session = raw.create()
    receipt = raw.finish(session)
    raw.actor = f"huron-web:{uuid4()}"
    raw.permissions = ["read"]
    revision_path = f"/api/raw-web/revisions/{receipt['id']}"
    assert raw.request("GET", revision_path + "/manifest").status_code == 200
    raw.target = {**raw.target, "name": "another-asset"}
    assert raw.request("GET", revision_path).status_code == 404
    assert raw.request("GET", revision_path + "/manifest").status_code == 404
    assert (
        raw.request("GET", f"/api/raw-web/datasets/{session['dataset_id']}/revisions").status_code
        == 404
    )


def test_commit_rejects_changed_metadata_and_wrong_acknowledgement(raw: RawWebClient) -> None:
    """Published metadata and revision identity cannot be changed by later signed requests."""
    session = raw.create()
    receipt = raw.finish(session)
    prefix = f"/api/raw-web/uploads/{session['id']}"
    changed = raw.request(
        "POST",
        prefix + "/commit",
        body={
            "manifest_sha256": session["manifest_sha256"],
            "metadata": {"title": "Changed after commit", "creators": ["Someone else"]},
        },
        headers={"if-match": '"0"', "idempotency-key": "changed-commit"},
    )
    assert changed.status_code == 409, changed.text
    wrong = raw.request("POST", prefix + "/registration", body={"revision_id": str(uuid4())})
    assert wrong.status_code == 403
    status = raw.request("GET", prefix).json()
    assert status["registration"]["state"] == "pending"
    assert status["registration"]["revision_id"] == receipt["id"]


def test_file_identity_cannot_be_substituted_between_owned_uploads(raw: RawWebClient) -> None:
    """Even an actor owning both uploads cannot write a file through the wrong session."""
    first = raw.create()
    raw.target = {**raw.target, "name": "other-owned-upload"}
    second = raw.create(key="second-target")
    mismatch = raw.request(
        "PUT",
        f"/api/raw-web/uploads/{second['id']}/files/{first['files'][0]['file_id']}/parts/1",
        data=b"real uploaded bytes",
    )
    assert mismatch.status_code == 403
    assert (
        raw.request("GET", f"/api/raw-web/uploads/{second['id']}").json()["files"][0][
            "completed_parts"
        ]
        == []
    )
