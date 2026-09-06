"""A small client over the ingest-session routes, driving one ``TestClient`` as one subject.

Shared by the ``unit`` ingest tests and, later, the acceptance suite, so the
HTTP mechanics of opening, reading and giving up a session are written once.
The client assumes ``root`` is bootstrapped as platform owner on the
``TestClient`` it wraps, the way every ingest test's fixture wires it.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

from huron.service.api.routes.v1.schema.ingest_sessions import ManifestFile

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi.testclient import TestClient
    from httpx import Response

_ADMIN = "root"


def _headers(subject: str, *, key: str | None = None) -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with an idempotency key.

    Args:
        subject: The ``X-Huron-Subject`` header value.
        key: The ``Idempotency-Key`` to send, or None for a fresh one.

    Returns:
        The headers a dev-header request needs.
    """
    return {"X-Huron-Subject": subject, "Idempotency-Key": key if key is not None else str(uuid4())}


def manifest_file(path: str, data: bytes) -> ManifestFile:
    """Declare a manifest file from its actual bytes.

    Args:
        path: The file's manifest path.
        data: The file's content; its size and digest are computed from it.

    Returns:
        The declared file, ready for a session's create body.
    """
    return ManifestFile(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def declared_file(path: str, size: int, sha256: str) -> ManifestFile:
    """Declare a manifest file from an already-known size and digest.

    Args:
        path: The file's manifest path.
        size: The file's declared size.
        sha256: The file's declared digest.

    Returns:
        The declared file, ready for a session's create body.
    """
    return ManifestFile(path=path, size=size, sha256=sha256)


class IngestClient:
    """Opens, reads and gives up ingest sessions as one subject, over one ``TestClient``.

    Attributes:
        subject: The dev-header subject every request is sent as.
        put_count: How many part uploads this client has issued.
    """

    def __init__(self, client: TestClient, *, subject: str = "bob") -> None:
        """Bind the client to one ``TestClient`` and one acting subject.

        Args:
            client: The ``TestClient`` every request is sent through.
            subject: The dev-header subject the client acts as; the owner
                of every session it opens.
        """
        self._client = client
        self.subject = subject
        self.put_count = 0

    def developer_dataset(self) -> tuple[str, str]:
        """Create an organization, a project and a raw dataset, binding ``subject`` as developer.

        Returns:
            The project's id and the dataset's id, both as strings.
        """
        organization = self._client.post(
            "/api/v1/organizations",
            json={"slug": "astro", "title": "Astro"},
            headers=_headers(_ADMIN),
        )
        assert organization.status_code == 201, organization.text
        organization_id = organization.json()["id"]
        project = self._client.post(
            f"/api/v1/organizations/{organization_id}/projects",
            json={"slug": "sims", "title": "Sims", "data_classification": "open"},
            headers=_headers(_ADMIN),
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        binding = self._client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": f"user:{self.subject}", "role": "developer"},
            headers=_headers(_ADMIN),
        )
        assert binding.status_code == 201, binding.text
        dataset = self._client.post(
            f"/api/v1/projects/{project_id}/datasets",
            json={
                "slug": "run-0001",
                "title": "Run 1",
                "profile_name": "mcnp-run",
                "profile_version": "1.0",
            },
            headers=_headers(self.subject),
        )
        assert dataset.status_code == 201, dataset.text
        return project_id, dataset.json()["id"]

    def create(
        self, dataset_id: str, files: Sequence[ManifestFile], *, key: str | None = None
    ) -> Response:
        """Open a session on ``dataset_id`` declaring ``files``.

        Args:
            dataset_id: The dataset the session opens on.
            files: The files the session's revision will hold.
            key: The ``Idempotency-Key`` to send, or None for a fresh one.

        Returns:
            The raw HTTP response.
        """
        return self._client.post(
            f"/api/v1/datasets/{dataset_id}/ingest-sessions",
            json={"files": [file.model_dump() for file in files]},
            headers=_headers(self.subject, key=key),
        )

    def get(self, session_id: str) -> Response:
        """Fetch one session's current view.

        Args:
            session_id: The session to read.

        Returns:
            The raw HTTP response.
        """
        return self._client.get(
            f"/api/v1/ingest-sessions/{session_id}", headers=_headers(self.subject)
        )

    def heartbeat(self, session_id: str) -> Response:
        """Renew one session's lease.

        Args:
            session_id: The session to renew.

        Returns:
            The raw HTTP response.
        """
        return self._client.post(
            f"/api/v1/ingest-sessions/{session_id}/heartbeat", headers=_headers(self.subject)
        )

    def abort(self, session_id: str) -> Response:
        """Abort one session as this client's subject.

        Args:
            session_id: The session to abort.

        Returns:
            The raw HTTP response.
        """
        return self._client.post(
            f"/api/v1/ingest-sessions/{session_id}/abort", headers=_headers(self.subject)
        )
