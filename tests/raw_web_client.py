"""Signed HTTP test client for the real Raw web transport."""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import jwt

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from httpx import Response

SECRET = "raw-web-tests-secret-with-at-least-32-bytes"
ACTOR = "huron-web:12345678-1234-4567-8123-123456789abc"
TARGET = {
    "endpoint": "http://polaris.test:8181",
    "realm": "POLARIS",
    "catalog": "heliophysics",
    "namespace": ["solar_wind", "ace"],
    "name": "uploaded_observations",
}


class RawWebClient:
    """Sign only test requests; all workflow state remains in the actual application."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.actor = ACTOR
        self.target = TARGET.copy()
        self.permissions = ["read", "write", "create"]

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        claims: dict[str, object] | None = None,
    ) -> Response:
        """Sign the exact bytes, path, actor and retry headers before an HTTP request."""
        payload = (
            json.dumps(body, separators=(",", ":")).encode() if body is not None else data or b""
        )
        bound_headers = {key.lower(): value for key, value in (headers or {}).items()}
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": "huron-web",
                "aud": "huron-raw",
                "sub": self.actor,
                "iat": now,
                "exp": now + 60,
                "method": method,
                "path": path,
                "body_sha256": hashlib.sha256(payload).hexdigest(),
                "headers": bound_headers,
                "target": self.target,
                "permissions": self.permissions,
                **(claims or {}),
            },
            SECRET,
            algorithm="HS256",
        )
        return self.client.request(
            method,
            path,
            content=payload,
            headers={
                **bound_headers,
                "authorization": f"Bearer {token}",
                "content-type": "application/json"
                if body is not None
                else "application/octet-stream",
            },
        )

    def create(
        self, data: bytes = b"real uploaded bytes", *, key: str = "upload-one"
    ) -> dict[str, Any]:
        """Create or resume an upload with a real checksum."""
        response = self.request(
            "POST",
            "/api/raw-web/uploads",
            body={
                "title": "Observed source",
                "description": "Independent evidence",
                "files": [
                    {
                        "path": "payload/science data.csv",
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "media_type": "text/csv",
                    }
                ],
            },
            headers={"idempotency-key": key},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def finish(
        self, session: dict[str, Any], data: bytes = b"real uploaded bytes"
    ) -> dict[str, Any]:
        """Transfer and commit actual bytes through the complete public workflow."""
        upload = f"/api/raw-web/uploads/{session['id']}"
        file = session["files"][0]
        for part in range(1, file["part_count"] + 1):
            offset = (part - 1) * session["part_bytes"]
            response = self.request(
                "PUT",
                f"{upload}/files/{file['file_id']}/parts/{part}",
                data=data[offset : offset + session["part_bytes"]],
            )
            assert response.status_code == 200, response.text
        if file["part_count"] > 1:
            complete = self.request("POST", f"{upload}/files/{file['file_id']}/complete")
            assert complete.status_code == 200, complete.text
        verified = self.request("POST", f"{upload}/verify")
        assert verified.status_code == 200, verified.text
        response = self.request(
            "POST",
            f"{upload}/commit",
            body={
                "manifest_sha256": session["manifest_sha256"],
                "metadata": {"title": "Observed source", "creators": ["NASA scientist"]},
            },
            headers={
                "idempotency-key": f"commit-{session['id']}",
                "if-match": verified.headers["etag"],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()
