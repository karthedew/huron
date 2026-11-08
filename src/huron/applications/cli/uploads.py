"""The tus client of ``huron push``: it uploads staged files to tusd through the upload proxy.

Each staged add gets one tus upload. The add records the upload's address and id before any
byte goes, so a later push continues the upload, or skips it when the service placed it. The
client hashes the file while it sends it and compares that hash with the ``Huron-Sha256``
receipt of the service.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from huron import __version__
from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import ApiError, CliError, ExitCode
from huron.applications.cli.state import StagedAdd
from huron.pkg.hashing import sha256_file

__all__ = ["CHUNK_SIZE", "POLL_INTERVAL", "UploadService", "Uploader"]

#: The bytes of one ``PATCH``.
CHUNK_SIZE = 64 * 1024 * 1024
#: The seconds between two reads of an upload that the service did not place yet.
POLL_INTERVAL = 5.0

_TUS_VERSION = "1.0.0"
_SHA256 = "Huron-Sha256"
#: The answers of a final ``PATCH`` after which the upload's state tells what happened.
_UNKNOWN_OUTCOME = frozenset({500, 502, 504})
_PLACED = frozenset({"placed", "committed"})
_GONE = frozenset({404, 410})
#: The seconds a finishing request waits beyond the hook timeout, for tusd and the proxy.
_FINISH_MARGIN = 60.0
_NEW_UPLOAD_HINT = "run `huron push` again. The next push starts a new upload of the file"


@dataclass(frozen=True, slots=True)
class UploadService:
    """Where tusd takes uploads, and how long it waits for the service to place one."""

    url: str
    hook_timeout: float

    @classmethod
    def from_health(cls, health: Mapping[str, Any]) -> UploadService:
        """Read ``uploads_url`` and ``upload_hook_timeout`` of ``GET /healthz``.

        Refuses when the service takes no uploads.
        """
        url = health.get("uploads_url")
        if url is None:
            raise CliError(
                "the Huron service does not accept uploads",
                ExitCode.FAILED,
                hint="the service administrator must set `lake_path` and `uploads_url`",
            )
        return cls(str(url), float(health["upload_hook_timeout"]))


class Uploader:
    """Uploads staged files to tusd as the logged-in user.

    ``token`` gives the Huron token for each request, ``sleep`` waits between two reads of an
    upload's state and ``report`` prints one progress line.
    """

    def __init__(
        self,
        http: httpx.Client,
        api: ApiClient,
        token: Callable[[], str],
        service: UploadService,
        *,
        sleep: Callable[[float], None],
        report: Callable[[str], None],
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        self._http = http
        self._api = api
        self._token = token
        self._service = service
        self._sleep = sleep
        self._report = report
        self._chunk_size = chunk_size
        # The request that finishes an upload waits while the service hashes and places it.
        self._finish_timeout = httpx.Timeout(
            30.0, connect=10.0, read=service.hook_timeout + _FINISH_MARGIN
        )

    def upload(self, collection_id: str, add: StagedAdd, save: Callable[[], None]) -> None:
        """Upload the file of ``add`` and set its ``sha256`` from the service's receipt.

        An upload that an earlier push started continues where it stopped, and one that the
        service placed with the same bytes is not sent again. ``save`` stores the stage; the
        uploader calls it each time it changes the upload that ``add`` records.
        """
        _check_source(add)
        if add.upload_id is not None and self._resume(add, save):
            return
        self._create(collection_id, add, save)

    def _resume(self, add: StagedAdd, save: Callable[[], None]) -> bool:
        """Finish or skip the recorded upload of ``add``; ``False`` when a new one must start."""
        assert add.upload_id is not None
        upload = self._state(add.upload_id)
        state = None if upload is None else upload["state"]
        if upload is not None and state in _PLACED:
            local = sha256_file(Path(add.source))[1]
            if upload["sha256"] == local:
                add.sha256 = local
                self._report(f"{add.rel_path} is on the service from an earlier push")
                return True
        if state == "pending":
            offset = self._offset(add)
            if offset is not None:
                self._send(add, offset, save)
                return True
        return False

    def _create(self, collection_id: str, add: StagedAdd, save: Callable[[], None]) -> None:
        metadata = {"collection": collection_id, "rel_path": add.rel_path}
        headers = {"Upload-Length": str(add.size), "Upload-Metadata": _metadata(metadata)}
        if add.size == 0:
            # tusd finishes an empty upload in the creation request.
            answer = self._finishing("POST", self._service.url, headers)
            if answer is None:
                raise CliError(
                    f"the upload service did not answer the creation of {add.rel_path} in time",
                    ExitCode.FAILED,
                    hint=_NEW_UPLOAD_HINT,
                )
            response = answer
        else:
            response = self._request("POST", self._service.url, headers)
        location = response.headers.get("Location")
        if location is None:
            _check(response)
            raise CliError("the upload service did not give an upload address", ExitCode.FAILED)
        add.upload_url = urljoin(self._service.url, location)
        add.upload_id = PurePosixPath(urlsplit(add.upload_url).path).name
        save()
        if add.size == 0:
            self._finish(add, response, hashlib.sha256().hexdigest(), save)
            return
        _check(response)
        self._send(add, 0, save)

    def _send(self, add: StagedAdd, offset: int, save: Callable[[], None]) -> None:
        """Send the bytes of ``add`` from ``offset``; the bytes before it only go into the hash."""
        assert add.upload_url is not None
        digest = hashlib.sha256()
        position = 0
        with Path(add.source).open("rb") as handle:
            while position < add.size:
                end = offset if position < offset else add.size
                block = handle.read(min(self._chunk_size, end - position))
                if not block:
                    raise _changed(add)
                digest.update(block)
                start, position = position, position + len(block)
                if position <= offset:
                    continue
                headers = {
                    "Upload-Offset": str(start),
                    "Content-Type": "application/offset+octet-stream",
                }
                if position == add.size:
                    answer = self._finishing("PATCH", add.upload_url, headers, block)
                    self._finish(add, answer, digest.hexdigest(), save)
                    return
                response = self._request("PATCH", add.upload_url, headers, block)
                _check(response)
                self._report(f"sent {position} of {add.size} bytes of {add.rel_path}")
        self._settle(add, digest.hexdigest(), save)

    def _finish(
        self,
        add: StagedAdd,
        response: httpx.Response | None,
        local: str,
        save: Callable[[], None],
    ) -> None:
        """Read the receipt of the request that finished the upload.

        A request that timed out (``None``) tells as little as a 504, so the upload's state
        decides.
        """
        if response is None:
            self._settle(add, local, save)
            return
        received = response.headers.get(_SHA256)
        unknown = response.status_code in _UNKNOWN_OUTCOME
        if unknown or (response.is_success and received is None):
            self._settle(add, local, save)
            return
        _check(response)
        assert received is not None
        self._accept(add, received, local)

    def _settle(self, add: StagedAdd, local: str, save: Callable[[], None]) -> None:
        """Accept the upload once the service placed it; report why it did not place it.

        An upload that is not placed is forgotten, so the next push starts a new one.
        """
        assert add.upload_id is not None
        upload = self._wait(add.upload_id)
        if upload is not None and upload["state"] in _PLACED:
            self._accept(add, upload["sha256"], local)
            return
        add.upload_url = add.upload_id = None
        save()
        raise self._unplaced(add, upload)

    def _unplaced(self, add: StagedAdd, upload: dict[str, Any] | None) -> CliError:
        """The error for an upload that the service did not place."""
        if upload is None:
            return CliError(
                f"the service has no record of the upload of {add.rel_path}",
                ExitCode.STORAGE,
                hint=_NEW_UPLOAD_HINT,
            )
        if upload["state"] == "failed":
            failure = upload["failure"] or {}
            return CliError(
                f"the service did not place {add.rel_path}: {failure.get('message')}",
                ExitCode.STORAGE,
                code=failure.get("code"),
            )
        if upload["state"] == "terminated":
            return CliError(
                f"the upload of {add.rel_path} is terminated",
                ExitCode.STORAGE,
                hint=_NEW_UPLOAD_HINT,
            )
        seconds = math.ceil(self._service.hook_timeout)
        return CliError(
            f"the service did not place {add.rel_path} in {seconds} seconds",
            ExitCode.STORAGE,
            hint=_NEW_UPLOAD_HINT,
        )

    def _wait(self, upload_id: str) -> dict[str, Any] | None:
        """Read the upload until it is no longer pending, for at most the hook timeout."""
        waited = 0.0
        while True:
            upload = self._state(upload_id)
            pending = upload is not None and upload["state"] == "pending"
            if not pending or waited >= self._service.hook_timeout:
                return upload
            self._sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL

    def _accept(self, add: StagedAdd, received: str | None, local: str) -> None:
        if received != local:
            raise CliError(
                f"the service hash of {add.rel_path} is not the same as the local hash",
                ExitCode.STORAGE,
                hint="run `huron push` again",
            )
        add.sha256 = received
        self._report(f"uploaded {add.rel_path} ({add.size} bytes)")

    def _state(self, upload_id: str) -> dict[str, Any] | None:
        """The upload as the API records it; ``None`` when the API does not know it."""
        try:
            upload: dict[str, Any] = self._api.get(f"/api/v1/uploads/{upload_id}")
        except ApiError as error:
            if error.code == "UPLOAD_NOT_FOUND":
                return None
            raise
        return upload

    def _offset(self, add: StagedAdd) -> int | None:
        """The bytes tusd holds of the recorded upload; ``None`` when tusd does not have it."""
        assert add.upload_url is not None
        response = self._request("HEAD", add.upload_url, {})
        if response.status_code in _GONE:
            return None
        _check(response)
        return int(response.headers["Upload-Offset"])

    def _request(
        self, method: str, url: str, headers: dict[str, str], content: bytes | None = None
    ) -> httpx.Response:
        try:
            return self._send_request(method, url, headers, content, self._http.timeout)
        except httpx.TransportError as error:
            raise self._unreachable(error) from error

    def _finishing(
        self, method: str, url: str, headers: dict[str, str], content: bytes | None = None
    ) -> httpx.Response | None:
        """Send a request that can finish an upload; ``None`` when its answer is too late."""
        try:
            return self._send_request(method, url, headers, content, self._finish_timeout)
        except httpx.ReadTimeout:
            return None
        except httpx.TransportError as error:
            raise self._unreachable(error) from error

    def _send_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        content: bytes | None,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        sent = {
            "Tus-Resumable": _TUS_VERSION,
            "User-Agent": f"huron-cli/{__version__}",
            "Authorization": f"Bearer {self._token()}",
            **headers,
        }
        return self._http.request(method, url, headers=sent, content=content, timeout=timeout)

    def _unreachable(self, error: httpx.TransportError) -> CliError:
        return CliError(
            f"the upload service at {self._service.url} is unreachable: {error}",
            ExitCode.FAILED,
            hint="run `huron push` again. The next push continues the upload",
        )


def _check_source(add: StagedAdd) -> None:
    """Refuse a staged file that is gone or that changed its size after ``huron add``."""
    try:
        size = os.stat(add.source).st_size
    except OSError as error:
        raise _changed(add) from error
    if size != add.size:
        raise _changed(add)


def _changed(add: StagedAdd) -> CliError:
    return CliError(
        f"{add.source} changed after you staged it",
        ExitCode.USAGE,
        hint=f"to stage the file again, run `huron add {add.source}`",
    )


def _metadata(values: Mapping[str, str]) -> str:
    """The ``Upload-Metadata`` header: each key with its value in base64."""
    return ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in values.items()
    )


def _check(response: httpx.Response) -> None:
    """Raise the error of a refused tus request."""
    if response.is_success:
        return
    try:
        document = response.json()
    except ValueError:
        document = None
    if isinstance(document, dict) and "code" in document:
        raise ApiError.from_problem(response.status_code, document)
    if response.status_code == 401:
        raise CliError(
            "the upload proxy did not accept your token",
            ExitCode.NOT_LOGGED_IN,
            hint="run `huron login`",
        )
    if response.status_code == 403:
        raise CliError(
            "this upload belongs to another user, or it no longer exists", ExitCode.FORBIDDEN
        )
    raise CliError(f"the upload service answered HTTP {response.status_code}", ExitCode.FAILED)
