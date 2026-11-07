"""Uploads through tusd: its blocking hooks, the proxy's authorization and an upload's state.

tusd forwards the client's ``Authorization`` header with every hook, so the hooks route verifies
the token itself and needs no secret of its own: each hook changes only what that user may
change. A refusal is a 200 answer that tells tusd the status and the problem document to give
the client. Only a failure the API may recover from (``LAKE_UNAVAILABLE``, ``STORAGE_FAILED``)
is an HTTP error, so tusd sends the hook again within its timeout.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from huron.applications.api.authorization import ActorDep, bearer_token, current_actor
from huron.applications.api.dependencies import LakeDep, RuntimeDep, UploadsDep, require_uploads
from huron.applications.api.disk import LakeDisk
from huron.applications.api.problems import PROBLEM_MEDIA_TYPE, problem_response
from huron.applications.api.routes.v1.schema.uploads import (
    ChangeFileInfo,
    HookRequest,
    HookResponse,
    HookType,
    HookUpload,
    HTTPResponse,
    UploadOut,
)
from huron.core.lake.bootstrap import Lake
from huron.core.lake.uploads.errors import UploadNotFound, UploadStateConflict
from huron.core.lake.uploads.models import Upload, UploadState
from huron.core.security.broker import TokenInvalid
from huron.core.security.rbac import Actor
from huron.core.storage import CollectionDirectoryMissing
from huron.pkg.errors import Forbidden, HuronError, Invalid, Unauthenticated

__all__ = ["RECEIPT_HEADERS", "router"]

#: The headers tusd adds to the response that finishes an upload.
RECEIPT_HEADERS = ("Huron-Upload-Id", "Huron-Sha256")

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(require_uploads)])

_CREATION_PATH = "/files/"
_UNPLACED = frozenset({UploadState.FAILED, UploadState.TERMINATED})


@router.post("/hooks", response_model_exclude_none=True)
async def hooks(
    hook: HookRequest, request: Request, runtime: RuntimeDep, lake: LakeDep, disk: UploadsDep
) -> HookResponse:
    """Answer one of tusd's blocking hooks: ``pre-create``, ``pre-finish`` or ``pre-terminate``.

    ``pre-create`` starts the upload row and names the tus upload after it. ``pre-finish``
    places the finished upload and answers its receipt in the ``Huron-Upload-Id`` and
    ``Huron-Sha256`` headers. ``pre-terminate`` ends an upload that was never placed.
    """
    try:
        actor = await current_actor(request, runtime)
        match hook.type:
            case HookType.PRE_CREATE:
                return await _create(lake, actor, hook.event.upload)
            case HookType.PRE_FINISH:
                return _receipt(await _finish(lake, disk, actor, hook.event.upload))
            case HookType.PRE_TERMINATE:
                await lake.uploads.terminate(actor, _upload_id(hook.event.upload))
                return HookResponse()
    except HuronError as error:
        if _retried(error):
            raise
        return _refusal(hook, error)


@router.get(
    "/auth",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={401: {"description": "No valid token"}, 403: {"description": "Not allowed"}},
)
async def authorize(
    request: Request,
    runtime: RuntimeDep,
    lake: LakeDep,
    method: Annotated[str, Header(alias="X-Original-Method")] = "",
    uri: Annotated[str, Header(alias="X-Original-URI")] = "",
) -> Response:
    """Whether the upload proxy may pass a request to tusd (204), or not (401, 403).

    A creation (``POST /files/``) needs a bearer token, which ``pre-create`` verifies. Any
    request on ``/files/<id>`` needs a valid token of the user who started upload ``<id>``.
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
    try:
        await lake.uploads.get(actor, upload_id)
    except UploadNotFound:
        refusal = Forbidden(
            "the upload does not exist, or another user started it", {"upload": str(upload_id)}
        )
        return problem_response(refusal, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{upload_id}")
async def get_upload(upload_id: uuid.UUID, actor: ActorDep, lake: LakeDep) -> UploadOut:
    """The state of an upload the caller started, its receipt and why it failed."""
    upload = await lake.uploads.get(actor, upload_id)
    return UploadOut.model_validate(upload.as_dict())


async def _create(lake: Lake, actor: Actor, upload: HookUpload) -> HookResponse:
    if upload.size_is_deferred or upload.is_partial or upload.is_final:
        raise Invalid(
            "an upload must declare its length, and it cannot be partial or a concatenation",
            {
                "size_is_deferred": upload.size_is_deferred,
                "is_partial": upload.is_partial,
                "is_final": upload.is_final,
            },
        )
    metadata = upload.metadata or {}
    collection, rel_path = metadata.get("collection"), metadata.get("rel_path")
    collection_id = None if collection is None else _canonical_id(collection)
    if collection_id is None or rel_path is None:
        raise Invalid(
            "the upload metadata must give the collection as a UUID and the rel_path",
            {"metadata": sorted(metadata)},
        )
    begun = await lake.uploads.begin(actor, collection_id, rel_path, upload.size)
    return HookResponse(change_file_info=ChangeFileInfo(id=str(begun.id)))


async def _finish(lake: Lake, disk: LakeDisk, actor: Actor, upload: HookUpload) -> Upload:
    upload_id = _upload_id(upload)
    current = await lake.uploads.get(actor, upload_id)
    if current.state in _UNPLACED:
        raise UploadStateConflict(
            current.state, (UploadState.PENDING, UploadState.PLACED, UploadState.COMMITTED)
        )
    if current.state is not UploadState.PENDING:
        return current
    destination = await lake.uploads.placement(actor, upload_id)
    return await disk.place(lake.uploads, actor, current, destination)


def _receipt(upload: Upload) -> HookResponse:
    assert upload.sha256 is not None
    header = dict(zip(RECEIPT_HEADERS, (str(upload.id), upload.sha256), strict=True))
    return HookResponse(http_response=HTTPResponse(header=header))


def _retried(error: HuronError) -> bool:
    """Whether tusd should send the hook again: a server failure the upload did not record.

    A missing collection directory fails the upload, so another call cannot do better.
    """
    return error.status >= status.HTTP_500_INTERNAL_SERVER_ERROR and not isinstance(
        error, CollectionDirectoryMissing
    )


def _refusal(hook: HookRequest, error: HuronError) -> HookResponse:
    instance = hook.event.http_request.uri or None
    response = HTTPResponse(
        status_code=error.status,
        header={"Content-Type": PROBLEM_MEDIA_TYPE},
        body=json.dumps(error.problem(instance)),
    )
    return HookResponse(
        http_response=response,
        reject_upload=True if hook.type is HookType.PRE_CREATE else None,
        reject_termination=True if hook.type is HookType.PRE_TERMINATE else None,
    )


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
