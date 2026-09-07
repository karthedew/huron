"""A small client over the ingest-session routes, driving one ``TestClient`` as one subject.

Shared by the ``unit`` ingest tests and, later, the acceptance suite, so the
HTTP mechanics of opening, reading and giving up a session are written once.
The client assumes ``root`` is bootstrapped as platform owner on the
``TestClient`` it wraps, the way every ingest test's fixture wires it.
"""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING
from uuid import uuid4

from huron.service.api.routes.v1.schema.ingest_sessions import ManifestFile

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from typing import Any, BinaryIO

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
        organization_id: The organization :meth:`developer_dataset` last
            created, or None before it has run.
        project_id: The project :meth:`developer_dataset` last created, or
            None before it has run.
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
        self.organization_id: str | None = None
        self.project_id: str | None = None

    def developer_dataset(
        self,
        *,
        classification: str = "open",
        organization_slug: str = "astro",
        project_slug: str = "sims",
    ) -> tuple[str, str]:
        """Create an organization, a project and a raw dataset, binding ``subject`` as developer.

        Args:
            classification: The project's ``data_classification``.
            organization_slug: The organization's slug; vary it to create
                a second, independent hierarchy on the same client.
            project_slug: The project's slug; vary it the same way.

        Returns:
            The project's id and the dataset's id, both as strings.
        """
        organization = self._client.post(
            "/api/v1/organizations",
            json={"slug": organization_slug, "title": organization_slug.title()},
            headers=_headers(_ADMIN),
        )
        assert organization.status_code == 201, organization.text
        self.organization_id = organization.json()["id"]
        project = self._client.post(
            f"/api/v1/organizations/{self.organization_id}/projects",
            json={
                "slug": project_slug,
                "title": project_slug.title(),
                "data_classification": classification,
            },
            headers=_headers(_ADMIN),
        )
        assert project.status_code == 201, project.text
        self.project_id = project.json()["id"]
        binding = self._client.post(
            f"/api/v1/projects/{self.project_id}/bindings",
            json={"principal": f"user:{self.subject}", "role": "developer"},
            headers=_headers(_ADMIN),
        )
        assert binding.status_code == 201, binding.text
        dataset = self._client.post(
            f"/api/v1/projects/{self.project_id}/datasets",
            json={
                "slug": "run-0001",
                "title": "Run 1",
                "profile_name": "mcnp-run",
                "profile_version": "1.0",
            },
            headers=_headers(self.subject),
        )
        assert dataset.status_code == 201, dataset.text
        return self.project_id, dataset.json()["id"]

    def reader(self, subject: str) -> None:
        """Bind ``subject`` as a reader on the project ``developer_dataset`` last created.

        A reader holds ``data.read`` on every layer, raw included, at
        project scope.

        Args:
            subject: The dev-header subject to bind as a reader.
        """
        assert self.project_id is not None, "call developer_dataset (or committed) first"
        response = self._client.post(
            f"/api/v1/projects/{self.project_id}/bindings",
            json={"principal": f"user:{subject}", "role": "reader"},
            headers=_headers(_ADMIN),
        )
        assert response.status_code == 201, response.text

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

    def put_part(
        self,
        file_id: str,
        part: int,
        body: bytes | Iterable[bytes],
        *,
        content_length: int | None = None,
    ) -> Response:
        """Upload one part's bytes.

        Args:
            file_id: The file the part belongs to.
            part: The 1-based part number being sent.
            body: The part's bytes, or an iterable yielding them in
                chunks.
            content_length: The ``Content-Length`` to declare. Defaults to
                ``len(body)`` for a plain bytes body; a generator body with
                no explicit value is sent with no ``Content-Length``
                header at all, which the route refuses before reading it.

        Returns:
            The raw HTTP response.
        """
        headers = _headers(self.subject)
        length = content_length if content_length is not None else _byte_length(body)
        if length is not None:
            headers["Content-Length"] = str(length)
        self.put_count += 1
        return self._client.put(
            f"/api/v1/transfer/uploads/{file_id}/parts/{part}", content=body, headers=headers
        )

    def complete(self, file_id: str) -> Response:
        """Assemble and verify one file's uploaded parts.

        Args:
            file_id: The file to complete.

        Returns:
            The raw HTTP response.
        """
        return self._client.post(
            f"/api/v1/transfer/uploads/{file_id}/complete", headers=_headers(self.subject)
        )

    def upload(self, session: Mapping[str, Any], source: Callable[[str], BinaryIO]) -> int:
        """Send every missing part of every ``PENDING`` upload file the session's view lists.

        A file already ``COMPLETE``, or planned as a hardlink, is skipped
        entirely; a file with some parts already recorded sends only the
        parts ``completed_parts`` does not already list.

        Args:
            session: A session view, as returned by ``create`` or ``get``.
            source: Given a manifest path, opens the file to read that
                path's bytes from; closed once its parts are read.

        Returns:
            The number of ``PUT`` requests this call issued.
        """
        issued = 0
        part_bytes = session["part_bytes"]
        for file in session["files"]:
            if file["action"] != "upload" or file["state"] == "COMPLETE":
                continue
            completed = set(file["completed_parts"])
            missing = [p for p in range(1, file["part_count"] + 1) if p not in completed]
            if not missing:
                continue
            with source(file["path"]) as handle:
                for part in missing:
                    offset = (part - 1) * part_bytes
                    length = part_bytes if part < file["part_count"] else file["size"] - offset
                    handle.seek(offset)
                    data = handle.read(length)
                    response = self.put_part(file["file_id"], part, data)
                    assert response.status_code == 200, response.text
                    issued += 1
        return issued

    def verify(self, session_id: str) -> Response:
        """Link every unchanged file from the parent and move to VERIFYING.

        Args:
            session_id: The session to verify.

        Returns:
            The raw HTTP response.
        """
        return self._client.post(
            f"/api/v1/ingest-sessions/{session_id}/verify", headers=_headers(self.subject)
        )

    def commit(
        self,
        session_id: str,
        etag: int,
        metadata: Mapping[str, Any],
        *,
        key: str | None = None,
    ) -> Response:
        """Commit a verified session, publishing its revision.

        The session's currently declared manifest digest is read back with
        a ``GET`` first, so a caller need only carry the etag and the
        metadata it wants to submit.

        Args:
            session_id: The session to commit.
            etag: The version to send as ``If-Match``.
            metadata: The descriptive metadata submission.
            key: The ``Idempotency-Key`` to send, or None for a fresh one.

        Returns:
            The raw HTTP response.
        """
        manifest_sha256 = self.get(session_id).json()["manifest_sha256"]
        return self._client.post(
            f"/api/v1/ingest-sessions/{session_id}/commit",
            json={"manifest_sha256": manifest_sha256, "metadata": metadata},
            headers={**_headers(self.subject, key=key), "If-Match": f'"{etag}"'},
        )

    def upload_revision(
        self, dataset_id: str, files: Sequence[tuple[str, bytes]]
    ) -> dict[str, Any]:
        """Ingest one revision end to end: create, upload, complete, verify and commit it.

        Every declared file is uploaded from its bytes, using whatever
        plan the create response returns - a file the parent already
        holds is skipped, exactly as :meth:`upload` does; a multipart
        upload file is completed once every part has landed.

        Args:
            dataset_id: The dataset the revision is added to.
            files: Each file's manifest path paired with its complete
                bytes.

        Returns:
            The committed revision's view, as JSON.
        """
        sources = dict(files)
        session = self.create(dataset_id, [manifest_file(path, data) for path, data in files])
        assert session.status_code == 201, session.text
        body = session.json()
        self.upload(body, lambda path: io.BytesIO(sources[path]))
        for file in body["files"]:
            if file["action"] == "upload" and file["part_count"] > 1:
                completion = self.complete(file["file_id"])
                assert completion.status_code == 200, completion.text
        verified = self.verify(body["id"])
        assert verified.status_code == 200, verified.text
        verified_body = verified.json()
        committed = self.commit(
            verified_body["id"],
            verified_body["etag"],
            {"title": "Revision", "creators": [self.subject]},
        )
        assert committed.status_code == 201, committed.text
        return committed.json()

    def committed(
        self,
        files: Sequence[tuple[str, bytes]],
        *,
        classification: str = "open",
        organization_slug: str = "astro",
        project_slug: str = "sims",
    ) -> tuple[str, str]:
        """Create a dataset and commit one revision from ``files``, in a single call.

        Args:
            files: Each file's manifest path paired with its complete
                bytes.
            classification: The owning project's ``data_classification``.
            organization_slug: The organization's slug; vary it to create
                a second, independent hierarchy on the same client.
            project_slug: The project's slug; vary it the same way.

        Returns:
            The dataset's id and the committed revision's id, both as
            strings.
        """
        _, dataset_id = self.developer_dataset(
            classification=classification,
            organization_slug=organization_slug,
            project_slug=project_slug,
        )
        view = self.upload_revision(dataset_id, files)
        return dataset_id, view["id"]

    def download(
        self, revision_id: str, path: str, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        """Stream one revision file's bytes.

        Args:
            revision_id: The revision the file belongs to.
            path: The file's manifest path, exactly as declared - or, in a
                test of the path rules themselves, exactly as sent.
            headers: Extra headers beyond the dev-header credential, such
                as ``Range``.

        Returns:
            The raw HTTP response, its body already read.
        """
        request_headers = {**_headers(self.subject), **(headers or {})}
        with self._client.stream(
            "GET", f"/api/v1/revisions/{revision_id}/files/{path}", headers=request_headers
        ) as response:
            response.read()
        return response


def _byte_length(body: bytes | Iterable[bytes]) -> int | None:
    """Return a plain bytes body's length, or None for anything else.

    Args:
        body: The candidate part body.

    Returns:
        ``len(body)`` when ``body`` is bytes, otherwise None - a generator
        body's true length is not known without consuming it.
    """
    return len(body) if isinstance(body, bytes) else None
