"""A fake upload endpoint for CLI tests: nginx's authorization and tusd, in one mock transport.

Each request first asks the in-process service's auth route, as nginx does. tusd's part keeps
the bytes and the ``.info`` file in the in-memory lake's ``.tus-uploads`` and sends its hooks to
the service, which seals the upload into the object area.
"""

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx

from huron.core.storage import UPLOADS, Storage
from tests.support.tusd import HOOKS, hook_body, upload_body

#: The public tus endpoint the fake serves, as ``uploads_url`` names it.
TUS_URL = "http://tusd.test/files/"
_API = "http://huron.test"
_FILES = "/files/"
_TUS_VERSION = "1.0.0"
_OFFSET_STREAM = "application/offset+octet-stream"


@dataclass
class TusUpload:
    """What the fake tusd knows of one upload."""

    length: int
    offset: int = 0


class FakeTus:
    """nginx and tusd in front of ``service``, with the uploads in the lake ``lake``.

    The fault fields act once each, on the next request that they apply to:

    - ``refuse``: nginx answers the next request of a method (the key) with a status (the value)
      and no problem document, as for a refused token.
    - ``drop_after``: a ``PATCH`` keeps this many bytes, then the connection drops.
    - ``finish_status``: the final ``PATCH`` answers this status. With ``skip_finish``, tusd
      sends no ``pre-finish`` hook first, as when the hook timed out.
    - ``corrupt``: the received bytes change before ``pre-finish``.
    - ``location_base``: the next creation answers a ``Location`` with this base, not tusd's.
    - ``info_size``: the next creation writes this size into the ``.info`` file.
    - ``hold_lock``: the final ``PATCH`` leaves a ``.lock`` file and sends no ``pre-finish``,
      as when tusd died during the hook.
    - ``lose``: tusd runs the next request of this method in full, then its answer does not
      reach the client in time.

    As tusd does, it answers 412 to a request without ``Tus-Resumable: 1.0.0`` and 415 to a
    ``PATCH`` whose ``Content-Type`` is not ``application/offset+octet-stream``.
    """

    def __init__(self, service: httpx.BaseTransport, lake: Storage) -> None:
        self.transport = httpx.MockTransport(self.handle)
        self.uploads: dict[str, TusUpload] = {}
        self.requests: list[tuple[str, str]] = []
        self.refuse: dict[str, int] = {}
        self.drop_after: int | None = None
        self.finish_status: int | None = None
        self.skip_finish = False
        self.corrupt = False
        self.location_base: str | None = None
        self.info_size: int | None = None
        self.hold_lock = False
        self.lose: str | None = None
        self._service = service
        self._lake = lake
        self._upload_dir = UPLOADS

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one tus request as nginx and tusd do."""
        response = self._answer(request)
        if self.lose == request.method:
            self.lose = None
            raise httpx.ReadTimeout("the answer is late", request=request)
        return response

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        refused = self._authorize(request)
        if refused is not None:
            return refused
        if request.headers.get("Tus-Resumable") != _TUS_VERSION:
            return httpx.Response(412, headers={"Tus-Version": _TUS_VERSION})
        if request.method == "PATCH" and request.headers.get("Content-Type") != _OFFSET_STREAM:
            return httpx.Response(415)
        if request.url.path == _FILES and request.method == "POST":
            return self._create(request)
        upload_id = request.url.path.removeprefix(_FILES)
        upload = self.uploads.get(upload_id)
        if upload is None:
            return httpx.Response(404)
        if request.method == "HEAD":
            headers = {"Upload-Offset": str(upload.offset), "Upload-Length": str(upload.length)}
            return httpx.Response(200, headers=headers)
        return self._patch(request, upload_id, upload)

    def _authorize(self, request: httpx.Request) -> httpx.Response | None:
        status = self.refuse.pop(request.method, None)
        if status is None:
            headers = {
                "X-Original-Method": request.method,
                "X-Original-URI": request.url.raw_path.decode(),
                "Authorization": request.headers.get("Authorization", ""),
            }
            auth = httpx.Request("GET", f"{_API}/api/v1/uploads/auth", headers=headers)
            status = self._service.handle_request(auth).status_code
        if status in {401, 403}:
            return httpx.Response(status, text="<html>refused</html>")
        return None if status < 300 else httpx.Response(500)

    def _create(self, request: httpx.Request) -> httpx.Response:
        length = int(request.headers["Upload-Length"])
        metadata = _metadata(request.headers.get("Upload-Metadata", ""))
        upload = upload_body("", length, metadata)
        answer = self._hook(request, hook_body("pre-create", upload, "POST", _FILES))
        if answer.get("RejectUpload"):
            return _merged(httpx.Response(201), answer)
        upload_id = answer["ChangeFileInfo"]["ID"]
        self.uploads[upload_id] = TusUpload(length)
        self._lake.write_bytes(self._upload_dir.joinpath(upload_id), b"", 0o600)
        size, self.info_size = length if self.info_size is None else self.info_size, None
        info = {"ID": upload_id, "Size": size, "SizeIsDeferred": False, "Offset": 0}
        info_file = self._upload_dir.joinpath(f"{upload_id}.info")
        self._lake.write_bytes(info_file, json.dumps(info).encode(), 0o600)
        base, self.location_base = self.location_base or TUS_URL, None
        created = httpx.Response(201, headers={"Location": f"{base}{upload_id}"})
        if length == 0:
            return self._finish(request, upload_id, created)
        return created

    def _patch(self, request: httpx.Request, upload_id: str, upload: TusUpload) -> httpx.Response:
        if int(request.headers["Upload-Offset"]) != upload.offset:
            return httpx.Response(409)
        body = request.read()
        dropped, self.drop_after = self.drop_after, None
        if dropped is not None:
            body = body[:dropped]
        source = self._upload_dir.joinpath(upload_id)
        self._lake.write_bytes(source, (self._lake.read_bytes(source) or b"") + body, 0o600)
        upload.offset += len(body)
        if dropped is not None:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=request
            )
        answer = httpx.Response(204, headers={"Upload-Offset": str(upload.offset)})
        if upload.offset < upload.length:
            return answer
        return self._finish(request, upload_id, answer)

    def _finish(
        self, request: httpx.Request, upload_id: str, answer: httpx.Response
    ) -> httpx.Response:
        source = self._upload_dir.joinpath(upload_id)
        if self.corrupt:
            self.corrupt = False
            data = self._lake.read_bytes(source) or b""
            self._lake.write_bytes(source, bytes(byte ^ 0xFF for byte in data), 0o600)
        status, self.finish_status = self.finish_status, None
        skip, self.skip_finish = self.skip_finish, False
        if self.hold_lock:
            self.hold_lock, skip = False, True
            self._lake.write_bytes(self._upload_dir.joinpath(f"{upload_id}.lock"), b"1", 0o600)
        if not skip:
            upload = upload_body(upload_id, self.uploads[upload_id].length)
            hook = hook_body("pre-finish", upload, request.method, request.url.path)
            answer = _merged(answer, self._hook(request, hook))
        if status is None:
            return answer
        return httpx.Response(status, headers=answer.headers, content=answer.content)

    def _hook(self, request: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
        """Send a hook with the client's ``Authorization``; a route failure stops the upload."""
        headers = {"Authorization": request.headers.get("Authorization", "")}
        hook = httpx.Request("POST", f"{_API}{HOOKS}", json=body, headers=headers)
        response = self._service.handle_request(hook)
        if not response.is_success:
            return {"HTTPResponse": {"StatusCode": 500}}
        answer: dict[str, Any] = response.json()
        return answer


def _metadata(header: str) -> dict[str, str]:
    """The ``Upload-Metadata`` header, decoded."""
    pairs = (item.split(" ", 1) for item in header.split(",") if item)
    return {key: base64.b64decode(value).decode() for key, value in pairs}


def _merged(response: httpx.Response, answer: dict[str, Any]) -> httpx.Response:
    """tusd's response with a hook's ``HTTPResponse`` merged into it."""
    merged = answer.get("HTTPResponse") or {}
    headers = {**response.headers, **(merged.get("Header") or {})}
    body = merged.get("Body")
    content = response.content if body is None else body.encode()
    headers.pop("content-length", None)
    status = merged.get("StatusCode") or response.status_code
    return httpx.Response(status, headers=headers, content=content)
