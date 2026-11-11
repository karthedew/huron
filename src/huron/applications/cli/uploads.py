"""The tus client of ``huron push``: it uploads staged files to tusd through the upload proxy.

Each staged add gets one upload attempt. The add records the attempt's ID before the creation
and the upload ID after it, so a later push continues the upload, or skips it when the service
sealed it. The client builds each upload address from ``uploads_url`` and the upload ID, never
from the host of a ``Location`` header. It sends a file only when the file has the size and the
modification time that ``huron add`` recorded. The commit sends the sha256 that ``huron add``
recorded, and the service compares it with the sha256 of the sealed bytes.
"""

from __future__ import annotations

import base64
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlsplit

import httpx

from huron import __version__
from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import ApiError, CliError, ExitCode
from huron.applications.cli.localstate import StagedAdd
from huron.applications.cli.sources import open_source, source_changed

__all__ = ["CHUNK_SIZE", "POLL_INTERVAL", "UploadService", "Uploader"]

#: The most bytes of one ``PATCH``.
CHUNK_SIZE = 64 * 1024 * 1024
#: The seconds between two reads of an upload attempt that the service did not seal yet.
POLL_INTERVAL = 5.0

_TUS_VERSION = "1.0.0"
_STATE_HEADER = "Huron-Upload-State"
#: The answers of a final ``PATCH`` after which the attempt's state tells what happened.
_UNKNOWN_OUTCOME = frozenset({500, 502, 504})
_UNSEALED = frozenset({"receiving", "sealing"})
_GONE = frozenset({404, 410})
#: The seconds a finishing request waits beyond the hook timeout, for tusd and the proxy.
_FINISH_MARGIN = 60.0
_NEW_UPLOAD_HINT = "run `huron push` again. The next push starts a new upload of the file"


@dataclass(frozen=True, slots=True)
class UploadService:
    """Where tusd takes uploads, and how long it waits for one hook."""

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

    def address(self, upload_id: str) -> str:
        """The address of the upload ``upload_id``: ``uploads_url`` and the ID."""
        return f"{self.url.rstrip('/')}/{upload_id}"


class Uploader:
    """Uploads staged files to tusd as the logged-in user.

    ``token`` gives the Huron token for each request, ``sleep`` waits between two reads of an
    attempt's state and ``report`` prints one progress line.
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
        # The request that finishes an upload waits while the service seals it.
        self._finish_timeout = httpx.Timeout(
            30.0, connect=10.0, read=service.hook_timeout + _FINISH_MARGIN
        )

    def upload(self, collection_id: str, add: StagedAdd, save: Callable[[], None]) -> None:
        """Upload the file of ``add`` and mark its attempt ``ready`` once the service sealed it.

        The file must have the size and the modification time that ``huron add`` recorded. An
        upload that an earlier push started continues where it stopped, and one that the
        service sealed is not sent again. ``save`` stores the stage; the uploader calls it each
        time it changes the attempt that ``add`` records.
        """
        with open_source(add) as source:
            if add.attempt_id is not None and self._resume(add, source, save):
                return
            self._create(collection_id, add, source, save)

    def _resume(self, add: StagedAdd, source: BinaryIO, save: Callable[[], None]) -> bool:
        """Finish or skip the recorded attempt of ``add``; ``False`` when a new one must start.

        A new attempt starts when the service does not know the attempt, when it ended, and when
        tusd lost its bytes.
        """
        assert add.attempt_id is not None
        attempt = self._attempt(add.attempt_id)
        if attempt is None or add.upload_id not in (None, attempt["upload_id"]):
            return False
        add.upload_id, state = attempt["upload_id"], attempt["state"]
        if state == "ready":
            self._accept(add, earlier=True)
            return True
        if state == "sealing":
            self._settle(add, save)
            return True
        if state == "receiving":
            offset = self._offset(add)
            if offset is not None:
                self._send(add, source, offset, save)
                return True
        return False

    def _create(
        self, collection_id: str, add: StagedAdd, source: BinaryIO, save: Callable[[], None]
    ) -> None:
        add.attempt_id, add.upload_id, add.attempt_state = str(uuid.uuid4()), None, None
        save()
        metadata = {
            "attempt_id": add.attempt_id,
            "collection": collection_id,
            "rel_path": add.rel_path,
        }
        headers = {"Upload-Length": str(add.size), "Upload-Metadata": _metadata(metadata)}
        if add.size == 0:
            # tusd finishes an empty upload in the creation request.
            response = self._finishing("POST", self._service.url, headers)
            if response is None or response.status_code in _UNKNOWN_OUTCOME:
                self._settle(add, save)
                return
        else:
            response = self._request("POST", self._service.url, headers)
        _check(response)
        add.upload_id = _upload_id_of(response)
        save()
        if add.size == 0:
            self._finish(add, response, save)
            return
        self._send(add, source, 0, save)

    def _send(
        self, add: StagedAdd, source: BinaryIO, offset: int, save: Callable[[], None]
    ) -> None:
        """Send the bytes of ``add`` from ``offset``, read from its open ``source``."""
        assert add.upload_id is not None
        address = self._service.address(add.upload_id)
        source.seek(offset)
        position = offset
        while position < add.size:
            block = source.read(min(self._chunk_size, add.size - position))
            if not block:
                raise source_changed(add)
            start, position = position, position + len(block)
            headers = {
                "Upload-Offset": str(start),
                "Content-Type": "application/offset+octet-stream",
            }
            if position == add.size:
                self._finish(add, self._finishing("PATCH", address, headers, block), save)
                return
            _check(self._request("PATCH", address, headers, block))
            self._report(f"sent {position} of {add.size} bytes of {add.rel_path}")
        self._settle(add, save)

    def _finish(
        self, add: StagedAdd, response: httpx.Response | None, save: Callable[[], None]
    ) -> None:
        """Read the answer of the request that finished the upload.

        A request that timed out (``None``) tells as little as a 504, so the attempt's state
        decides. So does an answer that says the seal goes on.
        """
        if response is None or response.status_code in _UNKNOWN_OUTCOME:
            self._settle(add, save)
            return
        _check(response)
        if response.headers.get(_STATE_HEADER) == "ready":
            self._accept(add)
            return
        self._settle(add, save)

    def _settle(self, add: StagedAdd, save: Callable[[], None]) -> None:
        """Accept the upload once the service sealed it; report why it did not seal it.

        The attempt and its upload ID stay recorded while the seal can still end, so the next
        push reads the attempt again. An attempt that ended is forgotten, and the next push
        starts a new one.
        """
        assert add.attempt_id is not None
        attempt = self._wait(add.attempt_id)
        if attempt is not None and attempt["state"] == "ready":
            add.upload_id = attempt["upload_id"]
            self._accept(add)
            return
        if attempt is None or attempt["state"] not in _UNSEALED:
            add.attempt_id = add.upload_id = add.attempt_state = None
            save()
        raise self._unsealed(add, attempt)

    def _unsealed(self, add: StagedAdd, attempt: dict[str, Any] | None) -> CliError:
        """The error for an upload that the service did not seal."""
        if attempt is None:
            return CliError(
                f"the service has no record of the upload of {add.rel_path}",
                ExitCode.STORAGE,
                hint=_NEW_UPLOAD_HINT,
            )
        state = attempt["state"]
        if state == "failed":
            failure = attempt["failure"] or {}
            return CliError(
                f"the service did not seal {add.rel_path}: {failure.get('message')}",
                ExitCode.STORAGE,
                code=failure.get("code"),
            )
        if state in _UNSEALED:
            seconds = math.ceil(self._service.hook_timeout)
            return CliError(
                f"the service did not seal {add.rel_path} in {seconds} seconds",
                ExitCode.STORAGE,
                hint="run `huron push` again. The next push reads the state of the upload",
            )
        return CliError(
            f"the upload of {add.rel_path} is {state}", ExitCode.STORAGE, hint=_NEW_UPLOAD_HINT
        )

    def _wait(self, attempt_id: str) -> dict[str, Any] | None:
        """Read the attempt until it is sealed or ended, for at most the hook timeout."""
        waited = 0.0
        while True:
            attempt = self._attempt(attempt_id)
            unsealed = attempt is not None and attempt["state"] in _UNSEALED
            if not unsealed or waited >= self._service.hook_timeout:
                return attempt
            self._sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL

    def _accept(self, add: StagedAdd, *, earlier: bool = False) -> None:
        add.attempt_state = "ready"
        if earlier:
            self._report(f"{add.rel_path} is on the service from an earlier push")
        else:
            self._report(f"uploaded {add.rel_path} ({add.size} bytes)")

    def _attempt(self, attempt_id: str) -> dict[str, Any] | None:
        """The attempt as the API records it; ``None`` when the API does not know it."""
        try:
            attempt: dict[str, Any] = self._api.get(f"/api/v1/upload-attempts/{attempt_id}")
        except ApiError as error:
            if error.code == "NOT_FOUND":
                return None
            raise
        return attempt

    def _offset(self, add: StagedAdd) -> int | None:
        """The bytes tusd holds of the recorded upload; ``None`` when tusd does not have it."""
        assert add.upload_id is not None
        response = self._request("HEAD", self._service.address(add.upload_id), {})
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


def _metadata(values: Mapping[str, str]) -> str:
    """The ``Upload-Metadata`` header: each key with its value in base64."""
    return ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in values.items()
    )


def _upload_id_of(response: httpx.Response) -> str:
    """The upload ID that the last segment of the creation's ``Location`` names.

    Only the ID is used: the host of the header is never followed.
    """
    location = response.headers.get("Location")
    name = None if location is None else PurePosixPath(urlsplit(location).path).name
    try:
        return str(uuid.UUID(name or ""))
    except ValueError:
        raise CliError(
            "the upload service did not give the address of a new upload", ExitCode.FAILED
        ) from None


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
            "this upload belongs to another user, or it does not take bytes now",
            ExitCode.FORBIDDEN,
        )
    raise CliError(f"the upload service answered HTTP {response.status_code}", ExitCode.FAILED)
