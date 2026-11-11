"""tusd's side of an upload: the files it keeps in ``.tus-uploads`` and the hooks it sends."""

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from huron.core.storage import UPLOAD_DIR
from tests.support.api import Caller, Service, active_collection

HOOKS = "/api/v1/uploads/hooks"
AUTH = "/api/v1/uploads/auth"


def upload_body(
    upload_id: str = "",
    size: int = 0,
    metadata: dict[str, str] | None = None,
    **flags: bool,
) -> dict[str, Any]:
    """The ``Event.Upload`` of a hook.

    ``flags`` are tusd's ``SizeIsDeferred``, ``IsPartial`` and ``IsFinal``.
    """
    return {"ID": upload_id, "Size": size, "MetaData": metadata, "Offset": size, **flags}


def hook_body(
    hook_type: str,
    upload: dict[str, Any],
    method: str,
    uri: str,
    header: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """A tusd v2 hook request, as tusd sends it to the hooks endpoint."""
    request = {"Method": method, "URI": uri, "RemoteAddr": "10.0.0.7:5100", "Header": header or {}}
    return {"Type": hook_type, "Event": {"Upload": upload, "HTTPRequest": request}}


def creation_metadata(collection_id: str, rel_path: str, attempt_id: str) -> dict[str, str]:
    """The ``Upload-Metadata`` of a creation, decoded."""
    return {"attempt_id": attempt_id, "collection": collection_id, "rel_path": rel_path}


def problem_of(response: httpx.Response) -> dict[str, Any]:
    """The problem document a refusal hands to tusd, and its status."""
    refusal = response.json()["HTTPResponse"]
    assert refusal["Header"] == {"Content-Type": "application/problem+json"}
    problem: dict[str, Any] = json.loads(refusal["Body"])
    assert problem["status"] == refusal["StatusCode"]
    return problem


class FakeTusd[A: Caller]:
    """Stands in for tusd in front of the service: it writes the upload files and calls hooks.

    ``upload_dir`` is the service's ``.tus-uploads``. Each hook sends the forwarded
    ``Authorization`` of ``user``, or none for ``user=None``.
    """

    def __init__(self, api: A, lake: Path) -> None:
        self.api = api
        self.upload_dir = lake / UPLOAD_DIR

    async def send(self, user: str | None, body: dict[str, Any]) -> httpx.Response:
        """Send one hook request."""
        headers = {} if user is None else await self.api.headers(user)
        return await self.api.client.post(HOOKS, json=body, headers=headers)

    async def create(
        self,
        user: str | None,
        collection_id: str,
        rel_path: str,
        size: int,
        *,
        attempt_id: str | None = None,
        header: dict[str, list[str]] | None = None,
        **flags: bool,
    ) -> httpx.Response:
        """``pre-create`` of an upload of ``size`` bytes to ``rel_path`` of the collection."""
        metadata = creation_metadata(collection_id, rel_path, attempt_id or str(uuid.uuid4()))
        upload = upload_body("", size, metadata, **flags)
        return await self.send(user, hook_body("pre-create", upload, "POST", "/files/", header))

    async def begin(
        self,
        user: str,
        collection_id: str,
        rel_path: str,
        data: bytes,
        *,
        attempt_id: str | None = None,
    ) -> str:
        """Create an upload of ``data`` and receive all of its bytes; returns the upload id."""
        created = await self.create(user, collection_id, rel_path, len(data), attempt_id=attempt_id)
        assert created.status_code == 200, created.text
        upload_id: str = created.json()["ChangeFileInfo"]["ID"]
        self.receive(upload_id, data)
        return upload_id

    def receive(
        self, upload_id: str, data: bytes, *, locked: bool = False, size: int | None = None
    ) -> Path:
        """Write the upload's bytes and its ``.info`` file, as tusd's filestore does.

        ``locked`` adds the ``.lock`` file that tusd keeps while it works on the upload.
        ``size`` is the declared size in ``.info``, by default the size of ``data``: a smaller
        ``data`` is an upload that tusd still receives.
        """
        source = self.upload_dir / upload_id
        source.write_bytes(data)
        os.chmod(source, 0o600)
        info = self.upload_dir / f"{upload_id}.info"
        declared = len(data) if size is None else size
        document = {"ID": upload_id, "Size": declared, "SizeIsDeferred": False, "Offset": 0}
        info.write_text(json.dumps(document))
        os.chmod(info, 0o600)
        if locked:
            (self.upload_dir / f"{upload_id}.lock").write_text("1")
        return source

    async def finish(self, user: str | None, upload_id: str, size: int) -> httpx.Response:
        """``pre-finish`` of the upload, sent from its final ``PATCH``."""
        upload = upload_body(upload_id, size)
        uri = f"/files/{upload_id}"
        return await self.send(user, hook_body("pre-finish", upload, "PATCH", uri))

    async def authorize(self, user: str | None, method: str, uri: str) -> httpx.Response:
        """nginx's authorization of a request with ``method`` on ``uri``."""
        headers = {"X-Original-Method": method, "X-Original-URI": uri}
        if user is not None:
            headers |= await self.api.headers(user)
        return await self.api.client.get(AUTH, headers=headers)


@dataclass(frozen=True)
class UploadTarget:
    """An active collection with its directory on the lake, and tusd in front of the service."""

    collection_id: str
    version: int
    directory: Path
    tusd: FakeTusd[Service]


async def upload_target(api: Service, lake: Path) -> UploadTarget:
    """Collection ``run7`` in the seeded ``api``, the directory its activation made below
    ``lake``, and tusd.
    """
    collection = await active_collection(api)
    directory = lake.joinpath(*collection["path"].split("/"))
    return UploadTarget(collection["id"], collection["version"], directory, FakeTusd(api, lake))
