"""Uploads through tusd: its blocking hooks, the proxy's authorization and the cancel.

tusd forwards the client's ``Authorization`` header with every hook, so the hooks route verifies
the token itself and needs no secret of its own: each hook changes only what that user may
change. A missing or invalid token is a refusal with the 401 problem, not an HTTP 401, so tusd
passes the status to the client. A refusal is a 200 answer that tells tusd the status and the
problem document to give the client. Only a failure the API may recover from (for example
``LAKE_UNAVAILABLE`` or ``STORAGE_FAILED``) is an HTTP error, so tusd sends the hook again
within its timeout.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from huron.applications.api.authorization import ActorDep, bearer_token, current_actor
from huron.applications.api.dependencies import LakeDep, RuntimeDep, UploadsDep, require_uploads
from huron.applications.api.disk import SEAL_WAIT, wait_for
from huron.applications.api.problems import (
    PROBLEM_MEDIA_TYPE,
    problem_document,
    problem_response,
)
from huron.applications.api.routes.v1.schema.uploads import (
    ChangeFileInfo,
    HookHTTPRequest,
    HookRequest,
    HookResponse,
    HookType,
    HookUpload,
    HTTPResponse,
    UploadAttemptOut,
)
from huron.core.lake.uploads.errors import UploadIneligible, UploadNotFound
from huron.core.lake.uploads.models import AttemptState
from huron.core.security.broker import TokenInvalid
from huron.pkg.errors import Forbidden, HuronError, Invalid, NotFound, Unauthenticated

if TYPE_CHECKING:
    from huron.applications.api.runtime import Orchestration, Runtime
    from huron.core.lake.bootstrap import Lake
    from huron.core.lake.uploads.models import UploadAttempt
    from huron.core.security.rbac import Actor

__all__ = ["UPLOAD_STATE_HEADER", "router"]

#: The header that tusd adds to the response that finishes an upload: the attempt's state.
UPLOAD_STATE_HEADER = "Huron-Upload-State"

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(require_uploads)])

_CREATION_PATH = "/files/"
_OFFSET_STREAM = "application/offset+octet-stream"


@router.post("/hooks", response_model_exclude_none=True)
async def hooks(
    hook: HookRequest,
    request: Request,
    runtime: RuntimeDep,
    lake: LakeDep,
    orchestration: UploadsDep,
) -> HookResponse:
    """Answer one of tusd's blocking hooks: ``pre-create`` or ``pre-finish``.

    ``pre-create`` applies the creation rule of upload attempts and names the tus upload with
    the upload ID that Huron issued. ``pre-finish`` starts or joins the seal of the upload and
    waits for it at most 20 seconds. It then answers the state in the ``Huron-Upload-State``
    header: ``ready``, or ``sealing`` when the seal goes on and the client must read the
    attempt.
    """
    try:
        actor = await current_actor(request, runtime)
        if hook.type is HookType.PRE_CREATE:
            return await _create(runtime, lake, orchestration, actor, hook)
        return await _finish(runtime, orchestration, actor, hook.event.upload)
    except HuronError as error:
        if error.status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise
        return _refusal(hook, error.problem(_instance(hook)), error.status)


@router.get(
    "/auth",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={401: {"description": "No valid token"}, 403: {"description": "Not allowed"}},
)
async def authorize(
    request: Request,
    runtime: RuntimeDep,
    method: Annotated[str, Header(alias="X-Original-Method")] = "",
    uri: Annotated[str, Header(alias="X-Original-URI")] = "",
) -> Response:
    """Whether the upload proxy may pass a request to tusd (204), or not (401, 403).

    A creation (``POST /files/``) needs a bearer token, which ``pre-create`` verifies. A request
    on ``/files/<id>`` needs a valid token of the owner of the attempt whose current upload ID
    is ``<id>``, and the attempt must be ``receiving``. An allowed ``PATCH`` records activity on
    the attempt.
    """
    path = uri.partition("?")[0]
    if path == _CREATION_PATH and method == "POST":
        if bearer_token(request) is None:
            missing = Unauthenticated("the request has no Huron bearer token")
            return _unauthenticated(missing, request)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    upload_id = None
    if path.startswith(_CREATION_PATH):
        upload_id = _canonical_id(path.removeprefix(_CREATION_PATH))
    if upload_id is None:
        return problem_response(Forbidden("the path names no upload", {"path": path}), request)
    try:
        actor = await current_actor(request, runtime)
    except (Unauthenticated, TokenInvalid) as error:
        return _unauthenticated(error, request)
    if await _allowed(runtime, actor, upload_id, method):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    refusal = Forbidden(
        "the upload is not a current upload that receives bytes, or another user started it",
        {"upload": str(upload_id)},
    )
    return problem_response(refusal, request)


@router.post("/{upload_id}/cancel")
async def cancel_upload(
    upload_id: uuid.UUID, actor: ActorDep, runtime: RuntimeDep, orchestration: UploadsDep
) -> UploadAttemptOut:
    """Cancel the caller's upload attempt that issued ``upload_id``.

    ``upload_id`` can be any upload ID that Huron issued for the attempt. The attempt becomes
    ``cancelled``, and the API removes the tusd files of every upload ID of the attempt. An
    attempt that ended already stays as it is. A commit that holds or consumed the attempt is
    a conflict.
    """
    attempt = await _owned(runtime, actor, upload_id)
    cancelled = await runtime.attempts.cancel(actor, attempt.attempt_id)
    if cancelled.state is AttemptState.CANCELLED:
        await orchestration.cancelled(cancelled)
    return UploadAttemptOut.model_validate(cancelled.as_dict())


async def _create(
    runtime: Runtime, lake: Lake, orchestration: Orchestration, actor: Actor, hook: HookRequest
) -> HookResponse:
    upload = hook.event.upload
    _check_creation(hook)
    attempt_id, collection_id, rel_path = _creation_fields(upload)
    runtime.attempts.check_size(upload.size)
    existing = await _existing(runtime, actor, attempt_id)
    with_info = await _with_info(orchestration, existing)
    if _issues_new_id(existing, with_info, collection_id, rel_path, upload.size):
        view = await lake.collections.get(actor, collection_id)
        await orchestration.capacity.admit(view.organization, upload.size)
    begun = await runtime.attempts.begin(
        actor, attempt_id, collection_id, rel_path, upload.size, with_info=with_info
    )
    return HookResponse(change_file_info=ChangeFileInfo(id=str(begun.current_upload_id)))


async def _finish(
    runtime: Runtime, orchestration: Orchestration, actor: Actor, upload: HookUpload
) -> HookResponse:
    upload_id = _upload_id(upload)
    await _owned(runtime, actor, upload_id)
    sealed = await wait_for(orchestration.sealing.start(upload_id), SEAL_WAIT)
    if sealed is None:
        return _state_answer(AttemptState.SEALING)
    if sealed.current_upload_id == upload_id and sealed.state is AttemptState.READY:
        return _state_answer(AttemptState.READY)
    if sealed.current_upload_id == upload_id and sealed.failure is not None:
        failure = sealed.failure
        document = problem_document(failure.code, failure.message, {"upload": str(upload_id)})
        return _refusal_of_finish(document)
    refusal = UploadIneligible.for_seal(
        upload_id, sealed.state, superseded=sealed.current_upload_id != upload_id
    )
    return _refusal_of_finish(refusal.problem())


def _check_creation(hook: HookRequest) -> None:
    """Refuse a deferred length, a part or the final upload of a concatenation, and a creation
    that carries bytes.
    """
    upload, client = hook.event.upload, hook.event.http_request
    carries_bytes = client.first("Content-Type") == _OFFSET_STREAM or _length(client) > 0
    if upload.size_is_deferred or upload.is_partial or upload.is_final or carries_bytes:
        raise Invalid(
            "an upload must declare its length, it cannot be part of a concatenation, and its"
            " creation cannot carry bytes",
            {
                "size_is_deferred": upload.size_is_deferred,
                "is_partial": upload.is_partial,
                "is_final": upload.is_final,
                "carries_bytes": carries_bytes,
            },
        )


def _creation_fields(upload: HookUpload) -> tuple[uuid.UUID, uuid.UUID, str]:
    """The ``attempt_id``, the collection and the ``rel_path`` of the upload metadata."""
    metadata = upload.metadata or {}
    attempt_id = _canonical_id(metadata.get("attempt_id", ""))
    collection_id = _canonical_id(metadata.get("collection", ""))
    rel_path = metadata.get("rel_path")
    if attempt_id is None or collection_id is None or rel_path is None:
        raise Invalid(
            "the upload metadata must give the attempt_id and the collection as UUIDs, and the"
            " rel_path",
            {"metadata": sorted(metadata)},
        )
    return attempt_id, collection_id, rel_path


async def _existing(runtime: Runtime, actor: Actor, attempt_id: uuid.UUID) -> UploadAttempt | None:
    """The actor's attempt with ``attempt_id``, ``None`` before its first creation."""
    try:
        return await runtime.attempts.get(actor, attempt_id)
    except NotFound:
        return None


async def _with_info(
    orchestration: Orchestration, existing: UploadAttempt | None
) -> uuid.UUID | None:
    """The current upload ID of a ``receiving`` attempt when tusd made its ``.info`` file."""
    if existing is None or existing.state is not AttemptState.RECEIVING:
        return None
    current = existing.current_upload_id
    return current if await orchestration.sealing.has_info(current) else None


def _issues_new_id(
    existing: UploadAttempt | None,
    with_info: uuid.UUID | None,
    collection_id: uuid.UUID,
    rel_path: str,
    size: int,
) -> bool:
    """Whether the creation issues a new upload ID, which needs free space for its bytes.

    That is so for a new attempt, and for a ``receiving`` attempt with the same fields whose
    current upload ID has no ``.info`` file.
    """
    if existing is None:
        return True
    return (
        existing.has_fields(collection_id, rel_path, size)
        and existing.state is AttemptState.RECEIVING
        and with_info is None
    )


async def _allowed(runtime: Runtime, actor: Actor, upload_id: uuid.UUID, method: str) -> bool:
    """Whether the actor's request with ``method`` may reach tusd's upload ``upload_id``.

    An allowed ``PATCH`` records activity on the attempt, and the record decides.
    """
    if not await runtime.attempts.accepts(actor, upload_id):
        return False
    if method == "PATCH":
        return await runtime.attempts.touch(upload_id)
    return True


async def _owned(runtime: Runtime, actor: Actor, upload_id: uuid.UUID) -> UploadAttempt:
    """The attempt that issued ``upload_id``; another user's attempt is not found."""
    attempt = await runtime.attempts.find(upload_id)
    if attempt.subject != actor.subject:
        raise UploadNotFound(upload_id)
    return attempt


def _state_answer(state: AttemptState) -> HookResponse:
    """The answer that adds the attempt's ``state`` to tusd's response, with tusd's status."""
    return HookResponse(http_response=HTTPResponse(header={UPLOAD_STATE_HEADER: str(state)}))


def _refusal(hook: HookRequest, document: dict[str, object], code: int) -> HookResponse:
    response = HTTPResponse(
        status_code=code,
        header={"Content-Type": PROBLEM_MEDIA_TYPE},
        body=json.dumps(document),
    )
    reject = True if hook.type is HookType.PRE_CREATE else None
    return HookResponse(http_response=response, reject_upload=reject)


def _refusal_of_finish(document: dict[str, object]) -> HookResponse:
    response = HTTPResponse(
        status_code=int(str(document["status"])),
        header={"Content-Type": PROBLEM_MEDIA_TYPE},
        body=json.dumps(document),
    )
    return HookResponse(http_response=response)


def _instance(hook: HookRequest) -> str | None:
    return hook.event.http_request.uri or None


def _length(client: HookHTTPRequest) -> int:
    text = client.first("Content-Length") or "0"
    return int(text) if text.isdigit() else 0


def _upload_id(upload: HookUpload) -> uuid.UUID:
    upload_id = _canonical_id(upload.id)
    if upload_id is None:
        raise Invalid("the upload id is not a UUID", {"id": upload.id})
    return upload_id


def _canonical_id(text: str) -> uuid.UUID | None:
    """The UUID ``text`` names in its canonical form (lowercase, with hyphens), else ``None``."""
    try:
        parsed = uuid.UUID(text)
    except ValueError:
        return None
    return parsed if str(parsed) == text else None


def _unauthenticated(error: HuronError, request: Request) -> Response:
    response = problem_response(error, request)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response
