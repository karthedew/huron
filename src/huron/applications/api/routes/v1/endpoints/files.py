"""Recorded files, commits and the commit route."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep, RuntimeDep, UploadsDep
from huron.applications.api.disk import PUBLISH_WAIT, SEAL_WAIT, wait_for
from huron.applications.api.problems import saved_problem_response
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.preconditions import set_etag
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.applications.api.routes.v1.schema.files import (
    CommitIn,
    CommitOut,
    CommitPreviewOut,
    CommitRequestOut,
    FileOut,
)
from huron.core.lake.publications.models import (
    CommitAdd,
    CommitDraft,
    CommitOutcome,
    CommitRequest,
    CommitState,
    DraftAdd,
)
from huron.core.storage import StorageError
from huron.pkg.errors import Conflict, Invalid

if TYPE_CHECKING:
    from huron.applications.api.runtime import Orchestration

__all__ = ["STATUS_PATH", "router"]

#: The path of the saved state of a commit request; ``{request_id}`` is the client's ID.
STATUS_PATH = "/api/v1/commit-requests/{request_id}"

router = APIRouter(prefix="/collections/{collection_id}", tags=["files"])


@router.get("/files")
async def list_files(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[FileOut]:
    """Recorded files, sorted by case-folded path."""
    page = await lake.commits.list_files(actor, collection_id, cursor, limit)
    return page_of(FileOut, [r.as_dict() for r in page.items], page.next_cursor)


@router.post(
    "/commits",
    response_model=CommitRequestOut | CommitPreviewOut,
    responses={
        202: {
            "model": CommitRequestOut,
            "description": "The request is accepted and not published yet, or blocked. The"
            " Location header names its state.",
        }
    },
)
async def commit(
    collection_id: uuid.UUID,
    body: CommitIn,
    actor: ActorDep,
    runtime: RuntimeDep,
    orchestration: UploadsDep,
    request: Request,
    response: Response,
    dry_run: Annotated[
        bool,
        Query(
            description=(
                "Check the commit as a real one, but not its uploads (right, pending commit,"
                " base version, paths), and answer what it would make; change nothing. Adds"
                " may leave out sha256 and upload_id, and the body may leave out request_id."
            )
        ),
    ] = False,
) -> CommitRequestOut | CommitPreviewOut | Response:
    """Publish added and removed files, or refuse the whole commit.

    The answer is 200 when the commit succeeded, and 202 with the ``Location`` of the request's
    state when it does not end within 5 seconds, when a storage error stops it for now, or when
    an operator must resolve it. A commit that names an upload of the caller that is not ready
    first runs the API's own seal check of that upload. An upload of another user is never
    checked here: the commit refuses it as not found. The same request ID with the same body
    gets the saved outcome again.
    """
    if dry_run:
        preview = await runtime.publications.preview(actor, _draft(collection_id, body))
        return CommitPreviewOut.model_validate(preview.as_dict())
    commit_request = _commit_request(collection_id, body)
    orchestration.require_writer()
    named = [add.upload_id for add in commit_request.adds]
    await orchestration.sealing.settle(await runtime.attempts.unsealed(actor, named), SEAL_WAIT)
    outcome = await runtime.publications.submit(actor, commit_request)
    if outcome.pending:
        published = await _published(orchestration, outcome)
        outcome = published or await runtime.publications.status(actor, outcome.request_id)
    return _answer(outcome, request, response)


@router.get("/commits")
async def list_commits(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[CommitOut]:
    """Commits, newest first."""
    page = await lake.commits.list_commits(actor, collection_id, cursor, limit)
    return page_of(CommitOut, [c.as_dict() for c in page.items], page.next_cursor)


async def _published(orchestration: Orchestration, outcome: CommitOutcome) -> CommitOutcome | None:
    """The request after its publication when it ends within 5 seconds, else ``None``.

    A storage error leaves the request pending: the periodic loop continues it.
    """
    try:
        return await wait_for(orchestration.materializer.start(outcome), PUBLISH_WAIT)
    except StorageError:
        return None


def _answer(
    outcome: CommitOutcome, request: Request, response: Response
) -> CommitRequestOut | Response:
    """The answer to a commit whose request has ``outcome`` now."""
    if outcome.state is CommitState.SUCCEEDED:
        assert outcome.version is not None
        set_etag(response, outcome.version)
        return CommitRequestOut.model_validate(outcome.as_dict())
    if outcome.state is CommitState.REJECTED:
        assert outcome.refusal is not None
        refusal = outcome.refusal
        return saved_problem_response(refusal.code, refusal.detail, refusal.context, request)
    if outcome.state is CommitState.ABANDONED:
        raise Conflict(
            "an operator abandoned the commit request. Send the commit again with a new request ID",
            {"request_id": str(outcome.request_id), "state": str(outcome.state)},
        )
    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = STATUS_PATH.format(request_id=outcome.request_id)
    return CommitRequestOut.model_validate(outcome.as_dict())


def _commit_request(collection_id: uuid.UUID, body: CommitIn) -> CommitRequest:
    """The commit request of ``body``; a field that only a dry run can leave out must be there."""
    missing = [
        f"/adds/{index}/{name}"
        for index, add in enumerate(body.adds)
        for name, value in (("sha256", add.sha256), ("upload_id", add.upload_id))
        if value is None
    ]
    if body.request_id is None:
        missing.insert(0, "/request_id")
    if missing:
        raise Invalid(
            "a commit needs request_id, and each add needs sha256 and upload_id. Only a dry"
            " run can leave them out",
            {"missing": missing[:20]},
        )
    assert body.request_id is not None
    adds = tuple(
        CommitAdd(add.rel_path, add.size, str(add.sha256), add.upload_id)
        for add in body.adds
        if add.upload_id is not None
    )
    return CommitRequest(
        request_id=body.request_id,
        collection_id=collection_id,
        base_version=body.base_version,
        adds=adds,
        removes=tuple(body.removes),
        host=body.host,
        message=body.message,
    )


def _draft(collection_id: uuid.UUID, body: CommitIn) -> CommitDraft:
    return CommitDraft(
        collection_id=collection_id,
        base_version=body.base_version,
        adds=tuple(
            DraftAdd(add.rel_path, add.size, add.sha256, add.upload_id) for add in body.adds
        ),
        removes=tuple(body.removes),
    )
