"""The tus client of ``huron push``: it uploads staged files to tusd through the upload proxy.

Each staged add gets one upload attempt. The add records the attempt's ID before the creation,
and the upload ID and the attempt's state after each answer, so a push that stops keeps both
IDs. Before each creation and each resume the client reads the attempt on the service, and it
continues, waits for the seal or starts a new attempt from that state. It never forgets an
upload: only an attempt that ended is replaced by a new one.

The client builds each upload address from ``uploads_url`` and the upload ID, never from the
host of a ``Location`` header. It sends a file only when the file has the size and the
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
from typing import Any, BinaryIO, TypeGuard
from urllib.parse import urlsplit

import httpx

from huron import __version__
from huron.applications.cli.client import ApiClient
from huron.applications.cli.deadline import Deadline, DeadlinePassed, poll
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
#: The answers of a request that finishes an upload after which the attempt's state tells what
#: happened.
_UNKNOWN_OUTCOME = frozenset({500, 502, 504})
#: The transport errors of a request that reached the service but whose answer was lost: it
#: came too late, or the connection dropped while the service worked on it.
_LOST_ANSWER = (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError)
_UNSEALED = frozenset({"receiving", "sealing"})
#: The states of an attempt whose upload the client can still use; any other state ended it.
_LIVE = frozenset({"receiving", "sealing", "ready"})
_GONE = frozenset({404, 410})
#: The code of the creation refusal that names the attempt's state and its current upload ID.
_STATE_CONFLICT = "UPLOAD_STATE_CONFLICT"
#: The seconds a finishing request waits beyond the hook timeout, for tusd and the proxy.
_FINISH_MARGIN = 60.0
_NEW_UPLOAD_HINT = "run `huron push` again. The next push starts a new upload of the file"
_CONTINUE_HINT = "run `huron push` again. The next push continues the upload"


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

    ``token`` gives the Huron token for each request. ``deadline`` gives the deadline of one
    wait for a seal, which lasts the service's hook timeout. ``report`` prints one progress
    line.
    """

    def __init__(
        self,
        http: httpx.Client,
        api: ApiClient,
        token: Callable[[], str],
        service: UploadService,
        *,
        deadline: Callable[[float], Deadline],
        report: Callable[[str], None],
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        self._http = http
        self._api = api
        self._token = token
        self._service = service
        self._deadline = deadline
        self._report = report
        self._chunk_size = chunk_size
        # The request that finishes an upload waits while the service seals it.
        self._finish_timeout = httpx.Timeout(
            30.0, connect=10.0, read=service.hook_timeout + _FINISH_MARGIN
        )

    def upload(self, collection_id: str, add: StagedAdd, save: Callable[[], None]) -> None:
        """Upload the file of ``add`` until the service sealed it; its attempt is then ``ready``.

        The file must have the size and the modification time that ``huron add`` recorded.
        ``save`` stores the stage: the uploader calls it each time it changes what ``add``
        records, first with the attempt ID before the creation. An upload that an earlier push
        started continues where it stopped, and one that the service sealed is not sent again.
        """
        with open_source(add) as source:
            file = _File(collection_id, add, source, save)
            if add.attempt_id is None:
                self._start_attempt(file)
            self._follow(file, self._attempt(file))

    def _follow(self, file: _File, attempt: _Attempt | None, *, refused: bool = False) -> None:
        """Continue from the state of the attempt on the service; ``None`` before its creation.

        ``refused`` when the state comes from a refused creation, which must not create again.
        """
        if attempt is None:
            self._create(file)
        elif attempt.state not in _LIVE:
            self._start_attempt(file)
            self._follow(file, self._attempt(file))
        elif attempt.state == "ready":
            self._accept(file, attempt.upload_id, earlier=True)
        else:
            self._record(file, attempt.state, attempt.upload_id)
            if attempt.state == "sealing":
                self._settle(file)
            else:
                self._resume(file, may_create=not refused)

    def _start_attempt(self, file: _File) -> None:
        """Give the add a new attempt ID, and save it before any creation sends it."""
        add = file.add
        add.attempt_id, add.upload_id, add.attempt_state = str(uuid.uuid4()), None, None
        file.save()

    def _create(self, file: _File) -> None:
        """Create the upload of the recorded attempt, or follow the state of a refusal."""
        add = file.add
        assert add.attempt_id is not None
        metadata = {
            "attempt_id": add.attempt_id,
            "collection": file.collection_id,
            "rel_path": add.rel_path,
        }
        headers = {"Upload-Length": str(add.size), "Upload-Metadata": _metadata(metadata)}
        if add.size == 0:
            # tusd finishes an empty upload in the creation request.
            response = self._finishing("POST", self._service.url, headers)
            if not _decisive(response):
                self._settle(file)
                return
        else:
            response = self._request("POST", self._service.url, headers)
        refusal = _refusal_of(response)
        if refusal is not None:
            self._follow(file, refusal, refused=True)
            return
        _check(response)
        self._record(file, "receiving", _upload_id_of(response))
        if add.size == 0:
            self._finish(file, response)
        else:
            self._send(file, 0)

    def _resume(self, file: _File, *, may_create: bool) -> None:
        """Continue the current upload from the bytes that tusd holds.

        When tusd does not have the upload, a new creation under the same attempt ID asks the
        service for a new upload ID, if ``may_create``.
        """
        upload_id = file.add.upload_id
        assert upload_id is not None
        self._continue_from(file, self._offset(upload_id, missing_ok=may_create))

    def _continue_from(self, file: _File, offset: int | None) -> None:
        """Continue the current upload from ``offset``, the bytes that tusd holds.

        ``None`` when tusd does not have the upload: a new creation under the same attempt ID
        replaces it. A complete upload is not sent again; the push waits for its seal.
        """
        if offset is None:
            self._create(file)
        elif offset == file.add.size:
            self._settle(file)
        else:
            self._send(file, offset)

    def _send(self, file: _File, offset: int) -> None:
        """Send the bytes of the add from ``offset`` up to its size, read from its open file."""
        add = file.add
        assert add.upload_id is not None
        address = self._service.address(add.upload_id)
        file.source.seek(offset)
        position = offset
        while True:
            block = file.source.read(min(self._chunk_size, add.size - position))
            if not block:
                raise source_changed(add)
            start, position = position, position + len(block)
            headers = {
                "Upload-Offset": str(start),
                "Content-Type": "application/offset+octet-stream",
            }
            if position == add.size:
                answer = self._finishing("PATCH", address, headers, block)
                if _decisive(answer):
                    self._finish(file, answer)
                else:
                    self._follow_unclear(file, start, answer)
                return
            _check(self._request("PATCH", address, headers, block))
            self._report(f"sent {position} of {add.size} bytes of {add.rel_path}")

    def _finish(self, file: _File, response: httpx.Response) -> None:
        """Read the answer of the request that finished the upload.

        An answer that says the seal goes on is followed by reads of the attempt.
        """
        _check(response)
        if response.headers.get(_STATE_HEADER) == "ready":
            self._accept(file, file.add.upload_id)
            return
        self._settle(file)

    def _follow_unclear(
        self, file: _File, start: int, answer: httpx.Response | httpx.TransportError
    ) -> None:
        """Continue from the attempt's state after the final ``PATCH`` from offset ``start`` lost
        its answer, or got an ``answer`` that tells as little.

        A ``receiving`` attempt can lack bytes of that request, so a ``HEAD`` asks tusd for the
        upload:

        - The upload is complete: the push reads the attempt until the service sealed it or the
          hook timeout passed.
        - Bytes are missing and the request moved the offset forward: the push sends the rest
          from that offset, so each such send starts later in the file.
        - tusd no longer has the upload: a new creation under the same attempt ID replaces it,
          and the push sends the file from the start.

        When the request moved no byte, the push stops and keeps the IDs and the state for the
        next push. In each other state, a ``sealing`` attempt is read until the seal ends or the
        deadline passes. A ``ready`` attempt is accepted. An attempt that ended, or that the
        service does not know, stops the push with its error, and the IDs stay recorded.
        """
        deadline = self._deadline(self._service.hook_timeout)
        attempt = self._first_read(file, deadline)
        if attempt is None or attempt.state != "receiving" or attempt.upload_id is None:
            self._wait(file, deadline, attempt)
            return
        self._record(file, attempt.state, attempt.upload_id)
        offset = self._offset(attempt.upload_id, missing_ok=True)
        if offset is not None and offset <= start:
            if isinstance(answer, httpx.Response):
                raise _answered(answer, hint=_CONTINUE_HINT)
            raise self._unreachable(answer)
        self._continue_from(file, offset)

    def _settle(self, file: _File) -> None:
        """Read the attempt until the service sealed it, or until the hook timeout passed."""
        deadline = self._deadline(self._service.hook_timeout)
        self._wait(file, deadline, self._first_read(file, deadline))

    def _first_read(self, file: _File, deadline: Deadline) -> _Attempt | None:
        """The first read of the attempt in a wait for its seal until ``deadline``.

        A read that times out at the deadline ends the wait.
        """
        try:
            return self._attempt(file, deadline)
        except DeadlinePassed:
            raise self._late(file.add) from None

    def _wait(self, file: _File, deadline: Deadline, first: _Attempt | None) -> None:
        """Read the attempt after its read ``first`` until the service sealed it, or until
        ``deadline``.

        An attempt that is not sealed keeps its IDs and its last state, so the next push reads
        it again. A read that times out at the deadline ends the wait.
        """
        attempt = poll(
            first,
            lambda: self._attempt(file, deadline),
            _is_unsealed,
            deadline,
            POLL_INTERVAL,
        )
        if attempt is None:
            raise CliError(
                f"the service has no record of the upload of {file.add.rel_path}",
                ExitCode.STORAGE,
                hint=_NEW_UPLOAD_HINT,
            )
        if attempt.state == "ready":
            self._accept(file, attempt.upload_id)
            return
        self._record(file, attempt.state, attempt.upload_id)
        raise self._unsealed(file.add, attempt)

    def _unsealed(self, add: StagedAdd, attempt: _Attempt) -> CliError:
        """The error for an upload that the service did not seal."""
        if attempt.state == "failed":
            failure = attempt.failure or {}
            return CliError(
                f"the service did not seal {add.rel_path}: {failure.get('message')}",
                ExitCode.STORAGE,
                code=failure.get("code"),
            )
        if attempt.state in _UNSEALED:
            return self._late(add)
        return CliError(
            f"the upload of {add.rel_path} is {attempt.state}",
            ExitCode.STORAGE,
            hint=_NEW_UPLOAD_HINT,
        )

    def _late(self, add: StagedAdd) -> CliError:
        """The error for an upload that the service did not seal before the hook timeout."""
        seconds = math.ceil(self._service.hook_timeout)
        return CliError(
            f"the service did not seal {add.rel_path} in {seconds} seconds",
            ExitCode.STORAGE,
            hint="run `huron push` again. The next push reads the state of the upload",
        )

    def _accept(self, file: _File, upload_id: str | None, *, earlier: bool = False) -> None:
        self._record(file, "ready", upload_id)
        if earlier:
            self._report(f"{file.add.rel_path} is on the service from an earlier push")
        else:
            self._report(f"uploaded {file.add.rel_path} ({file.add.size} bytes)")

    def _record(self, file: _File, state: str, upload_id: str | None) -> None:
        """Record the attempt's state and current upload ID; save them when they changed."""
        add = file.add
        if (add.attempt_state, add.upload_id) != (state, upload_id):
            add.attempt_state, add.upload_id = state, upload_id
            file.save()

    def _attempt(self, file: _File, deadline: Deadline | None = None) -> _Attempt | None:
        """The attempt of the add as the API records it; ``None`` when the API does not know it."""
        try:
            found: dict[str, Any] = self._api.get(
                f"/api/v1/upload-attempts/{file.add.attempt_id}", deadline=deadline
            )
        except ApiError as error:
            if error.code == "NOT_FOUND":
                return None
            raise
        return _Attempt(str(found["state"]), found["upload_id"], found.get("failure"))

    def _offset(self, upload_id: str, *, missing_ok: bool) -> int | None:
        """The bytes tusd holds of an upload; ``None`` when tusd does not have it and
        ``missing_ok``.
        """
        response = self._request("HEAD", self._service.address(upload_id), {})
        if missing_ok and response.status_code in _GONE:
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
    ) -> httpx.Response | httpx.TransportError:
        """Send a request that can finish an upload; the transport error when its answer is
        lost.
        """
        try:
            return self._send_request(method, url, headers, content, self._finish_timeout)
        except _LOST_ANSWER as error:
            return error
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
        """The error for a request that got no answer from the upload service, with its
        transport error.
        """
        return CliError(
            f"the upload service at {self._service.url} is unreachable: {error}",
            ExitCode.FAILED,
            hint=_CONTINUE_HINT,
        )


@dataclass(frozen=True, slots=True)
class _File:
    """One staged add to upload, with its open source file and the function that saves it."""

    collection_id: str
    add: StagedAdd
    source: BinaryIO
    save: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _Attempt:
    """An upload attempt as the service gives it: its state and its current upload ID.

    A refused creation of an attempt that ended names no upload ID. ``failure`` is the problem
    of a ``failed`` attempt.
    """

    state: str
    upload_id: str | None
    failure: dict[str, Any] | None = None


def _decisive(answer: httpx.Response | httpx.TransportError) -> TypeGuard[httpx.Response]:
    """Whether ``answer`` tells how a request that finishes an upload ended; after any other
    answer the attempt's state tells.
    """
    return isinstance(answer, httpx.Response) and answer.status_code not in _UNKNOWN_OUTCOME


def _is_unsealed(attempt: _Attempt | None) -> bool:
    return attempt is not None and attempt.state in _UNSEALED


def _refusal_of(response: httpx.Response) -> _Attempt | None:
    """The attempt that a creation refusal of the attempt's state names; ``None`` for any other
    answer.
    """
    if response.status_code != httpx.codes.CONFLICT:
        return None
    try:
        document = response.json()
    except ValueError:
        return None
    if not isinstance(document, dict) or document.get("code") != _STATE_CONFLICT:
        return None
    context = document.get("context") or {}
    return _Attempt(str(context["state"]), context.get("upload_id"))


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
    raise _answered(response)


def _answered(response: httpx.Response, *, hint: str | None = None) -> CliError:
    """The error for an answer of the upload service that tells no more than its status."""
    return CliError(
        f"the upload service answered HTTP {response.status_code}", ExitCode.FAILED, hint=hint
    )
