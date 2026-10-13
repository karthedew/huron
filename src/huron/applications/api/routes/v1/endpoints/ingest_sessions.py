"""Ingest sessions: open one, read it, keep its lease alive, or give it up.

Two routers open a session - on an existing raw dataset, or by minting one
at intake - a third addresses a session already open by id, and a fourth
carries the part-upload transport. Every session-view response carries the
session's current ``etag`` as its ``ETag`` header, the value a later
``/commit`` names in ``If-Match``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from huron.applications.api.authorization import (
    CurrentVisibility,
    IngestDrive,
    UploadTarget,
    dataset_raw_writer,
    project_intake,
    session_overseer,
    session_owner,
    upload_owner,
)
from huron.applications.api.dependencies import Datasets as Repository
from huron.applications.api.dependencies import RawIngestion as Ingest
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.applications.api.routes.v1.schema.ingest_sessions import (
    CommitIngestSession,
    CreateIngestSession,
    CreateIngestSessionInProject,
    IngestFileView,
    IngestSessionView,
    ManifestFile,
)
from huron.applications.api.routes.v1.schema.revisions import RevisionView
from huron.applications.api.streams import body_chunks
from huron.core.catalog.types import Dataset
from huron.core.foundation.canonical import content_identity
from huron.core.foundation.retry import IdempotencyClaim, request_sha256
from huron.core.raw import RawIngestionService
from huron.core.raw.manifest import ManifestEntry
from huron.core.raw.retry import session_claim
from huron.core.raw.types import SessionLedger
from huron.core.security.principal import Principal

dataset_ingest_sessions = APIRouter(
    prefix="/datasets/{dataset_id}/ingest-sessions", tags=["ingest-sessions"]
)
project_ingest_sessions = APIRouter(
    prefix="/projects/{project_id}/ingest-sessions", tags=["ingest-sessions"]
)
router = APIRouter(prefix="/ingest-sessions", tags=["ingest-sessions"])
transfer = APIRouter(prefix="/transfer", tags=["transfer"])

ContentLengthHeader = Annotated[int, Header(alias="Content-Length")]

_MANIFEST_ERRORS = problem_response("the manifest is empty or breaks a path rule")
_SIZE_ERRORS = problem_response("a file, or the revision as a whole, exceeds the configured limit")


def _entries(files: list[ManifestFile]) -> tuple[ManifestEntry, ...]:
    """Turn declared manifest files into the domain's unvalidated entries.

    Args:
        files: The files a session's create body declares.

    Returns:
        One ``ManifestEntry`` per declared file, in the order given.
    """
    return tuple(
        ManifestEntry(
            path=item.path, size=item.size, sha256=item.sha256, media_type=item.media_type
        )
        for item in files
    )


def _session_view(ledger: SessionLedger, response: Response) -> IngestSessionView:
    """Render a session and its quoted ETag from the same ledger.

    Args:
        ledger: The session ledger to publish.
        response: The response carrying the session's ETag header.

    Returns:
        The session's public view.
    """
    response.headers["ETag"] = f'"{ledger.etag}"'
    return IngestSessionView.model_validate(ledger)


async def _open_session(
    ingest: RawIngestionService,
    dataset: Dataset,
    files: list[ManifestFile],
    *,
    actor: str,
    idempotency_key: str,
    response: Response,
) -> IngestSessionView:
    """Plan, reserve and stage a session on ``dataset``, then render its view.

    Args:
        ingest: The wired ingest service.
        dataset: The dataset the session opens on.
        files: The files the client declared.
        actor: The principal opening the session.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        response: The response to carry the session's ``ETag`` on.

    Returns:
        The new (or replayed) session's view.
    """
    entries = _entries(files)
    claim = session_claim(actor, idempotency_key, dataset.id, entries)
    ledger = await ingest.create(dataset.id, files=entries, claim=claim)
    return _session_view(ledger, response)


@dataset_ingest_sessions.post(
    "",
    status_code=201,
    responses={
        400: _MANIFEST_ERRORS,
        404: problem_response("no such dataset"),
        409: problem_response(
            "another session is already open, its entry layer is not raw, the manifest "
            "collides with an existing entry, the dataset already holds this manifest, or "
            "the idempotency key was reused for a different manifest"
        ),
        413: _SIZE_ERRORS,
    },
)
async def create_dataset_ingest_session(
    dataset_id: UUID,
    body: CreateIngestSession,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    ingest: Ingest,
    visibility: CurrentVisibility,
    actor: Annotated[Principal, Depends(dataset_raw_writer)],
    response: Response,
) -> IngestSessionView:
    """Open a raw ingest session on an existing dataset.

    Requires ``data.write`` on the dataset's raw layer; the dataset's
    entry layer must be ``raw``. Plans every declared file for a complete independent upload and
    locks the dataset until the
    session reaches a terminal state. Replaying the same
    ``Idempotency-Key`` with the same files returns the original session
    instead of a 409; reusing the key for a different manifest is refused.
    \f
    Args:
        dataset_id: The dataset the revision will belong to.
        body: The files the revision will hold.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The caller's authorized dataset reads.
        ingest: The wired ingest service.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.
        actor: The caller, whose subject scopes the idempotency claim.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The new session's view, in state UPLOADING.
    """
    dataset = await repository.get(dataset_id)
    return await _open_session(
        ingest,
        dataset,
        body.files,
        actor=actor.subject,
        idempotency_key=idempotency_key,
        response=response,
    )


@project_ingest_sessions.post(
    "",
    status_code=201,
    responses={
        400: _MANIFEST_ERRORS,
        404: problem_response("no such project"),
        409: problem_response(
            "another session is already open, the manifest collides with an existing entry, "
            "the dataset already holds this manifest, the idempotency key was reused for a "
            "different manifest, or the dataset slug already exists"
        ),
        413: _SIZE_ERRORS,
    },
)
async def create_project_ingest_session(
    project_id: UUID,
    body: CreateIngestSessionInProject,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    ingest: Ingest,
    visibility: CurrentVisibility,
    actor: Annotated[Principal, Depends(project_intake)],
    response: Response,
) -> IngestSessionView:
    """Mint a raw dataset under a project, then open its first ingest session.

    Requires ``data.write`` on the project's raw layer and
    ``dataset.create`` on the project; the minted dataset's entry layer is
    always ``raw``. One ``Idempotency-Key`` covers both writes: the dataset
    is created under a key derived from it, so a retry after a failure
    between the two replays the kept dataset and opens the session on it,
    while reusing the key for a different manifest is refused before a
    second dataset is ever minted.
    \f
    Args:
        project_id: The project the dataset is created under.
        body: The dataset to create and the files its first revision holds.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The caller's authorized dataset reads.
        ingest: The wired ingest service.
        visibility: The caller's discovery rights, used to resolve
            ``project_id``.
        actor: The caller, whose subject scopes both idempotency claims.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The new session's view, in state UPLOADING.
    """
    ledger = await ingest.create_in_project(
        project_id,
        slug=body.dataset.slug,
        title=body.dataset.title,
        description=body.dataset.description,
        profile_name=body.dataset.profile_name,
        profile_version=body.dataset.profile_version,
        files=_entries(body.files),
        idempotency_key=idempotency_key,
    )
    return _session_view(ledger, response)


@router.get("/{session_id}", responses={404: problem_response("no such ingest session")})
async def get_ingest_session(
    drive: Annotated[IngestDrive, Depends(session_overseer)], response: Response
) -> IngestSessionView:
    """Fetch one ingest session and its ledger.

    The owner, or a project admin, may read a session. An id that is
    absent, or whose dataset is not discoverable, is 404; a visible
    caller who is neither the owner nor a project admin is 403.
    \f
    Args:
        drive: The caller's resolved standing on the session.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The session's current view.
    """
    return _session_view(drive.ledger, response)


@router.post(
    "/{session_id}/heartbeat",
    responses={
        404: problem_response("no such ingest session"),
        409: problem_response("the session's lease has lapsed, or it is terminal"),
    },
)
async def heartbeat_ingest_session(
    drive: Annotated[IngestDrive, Depends(session_owner)], ingest: Ingest, response: Response
) -> IngestSessionView:
    """Renew a session's lease.

    Only the owner may renew it, and only while their raw-write binding
    still stands. The lease moves forward; ``etag`` does not.
    \f
    Args:
        drive: The caller's resolved standing on the session.
        ingest: The wired ingest service.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The session's view, with its lease renewed.
    """
    ledger = await ingest.heartbeat(drive.ledger.id)
    return _session_view(ledger, response)


@router.post(
    "/{session_id}/abort",
    responses={
        404: problem_response("no such ingest session"),
        409: problem_response("the session is already COMMITTING or terminal"),
        412: problem_response("the session moved under the caller"),
    },
)
async def abort_ingest_session(
    drive: Annotated[IngestDrive, Depends(session_overseer)], ingest: Ingest, response: Response
) -> IngestSessionView:
    """Abort a session, releasing the dataset lock it holds.

    The owner may abort their own session; a project admin may force-abort
    anyone's. Never from COMMITTING: once a commit has begun it either
    becomes durable or fails, never half of each.
    \f
    Args:
        drive: The caller's resolved standing on the session.
        ingest: The wired ingest service.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The session's view, in state ABORTED.
    """
    ledger = await ingest.abort(drive.ledger.id)
    return _session_view(ledger, response)


_UPLOAD_ERRORS = problem_response(
    "the content length disagreed with the plan, the stream ended short or long, the "
    "file's observation disagreed with the manifest, or the client disconnected mid-body"
)


@transfer.put(
    "/uploads/{file_id}/parts/{part}",
    responses={
        400: _UPLOAD_ERRORS,
        404: problem_response("no such file, or the part is outside its planned range"),
        409: problem_response(
            "the session's lease has lapsed, it is not UPLOADING, or the file cannot "
            "receive a part in its current state"
        ),
    },
)
async def upload_part(
    part: int,
    request: Request,
    content_length: ContentLengthHeader,
    target: Annotated[UploadTarget, Depends(upload_owner)],
    ingest: Ingest,
) -> IngestFileView:
    """Stream one part's bytes into its range of the file's payload.

    ``Content-Length`` must equal the part's planned length; a request with
    no ``Content-Length`` - a chunked body - is refused before a byte is
    read, since the part's length must be known up front. The owner alone
    may drive an upload, and only while their raw-write binding stands.
    \f
    Args:
        part: The 1-based part number being uploaded.
        request: The request whose body carries the part's bytes.
        content_length: The declared length of the part.
        target: The caller's resolved standing on the file.
        ingest: The wired ingest service.

    Returns:
        The file's view once the part is recorded.
    """
    chunks = body_chunks(request)
    file = await ingest.receive_part(
        target.ledger.id, target.file.file_id, part, chunks, content_length=content_length
    )
    return IngestFileView.model_validate(file)


@transfer.post(
    "/uploads/{file_id}/complete",
    responses={
        400: problem_response(
            "the assembled bytes disagree with the manifest; every part must be re-sent"
        ),
        409: problem_response(
            "the session's lease has lapsed, it is not UPLOADING, or the file is not "
            "fully received or is already complete"
        ),
    },
)
async def complete_upload(
    target: Annotated[UploadTarget, Depends(upload_owner)], ingest: Ingest
) -> IngestFileView:
    """Assemble and verify one file's uploaded parts.

    Every part the plan calls for must already be recorded before this
    succeeds; a mismatch against the manifest discards the assembled bytes
    and resets the file to no parts recorded. The owner alone may drive it.
    \f
    Args:
        target: The caller's resolved standing on the file.
        ingest: The wired ingest service.

    Returns:
        The file's view once it is COMPLETE.
    """
    file = await ingest.complete_file(target.ledger.id, target.file.file_id)
    return IngestFileView.model_validate(file)


@router.post(
    "/{session_id}/verify",
    responses={
        400: problem_response("not every planned file is complete"),
        404: problem_response("no such ingest session"),
        409: problem_response("the session's lease has lapsed, or it is not UPLOADING"),
        412: problem_response("the session moved under the caller"),
    },
)
async def verify_ingest_session(
    drive: Annotated[IngestDrive, Depends(session_owner)], ingest: Ingest, response: Response
) -> IngestSessionView:
    """Verify every submitted file and move the session to VERIFYING.

    Every submitted file must already be COMPLETE; anything still pending
    is refused with the incomplete paths named. The owner alone may drive
    it, and only while their raw-write binding stands.
    \f
    Args:
        drive: The caller's resolved standing on the session.
        ingest: The wired ingest service.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The session's view, in state VERIFYING.
    """
    ledger = await ingest.verify(drive.ledger.id)
    return _session_view(ledger, response)


@router.post(
    "/{session_id}/commit",
    status_code=201,
    responses={
        400: problem_response("the declared manifest digest disagrees with the session's"),
        404: problem_response("no such ingest session"),
        409: problem_response(
            "the session's lease has lapsed, it is not VERIFYING or COMMITTING, the "
            "metadata submission violates the registered schema, the idempotency key was "
            "reused for a different request"
        ),
        412: problem_response("the If-Match version disagrees with the session's current etag"),
        422: problem_response("the If-Match header is malformed"),
        500: problem_response("storage and the catalog disagree about a committed revision"),
    },
)
async def commit_ingest_session(
    session_id: UUID,
    body: CommitIngestSession,
    if_match: IfMatchHeader,
    idempotency_key: IdempotencyHeader,
    drive: Annotated[IngestDrive, Depends(session_owner)],
    ingest: Ingest,
) -> RevisionView:
    """Publish a verified session's envelope as a committed revision.

    Requires the current ``If-Match`` version, unless the session is
    already COMMITTED, in which case the original revision is returned
    unchanged. Replaying the same ``Idempotency-Key`` with the same
    ``manifest_sha256`` and metadata returns the original revision instead
    of a second commit; reusing the key for a different request is
    refused. The owner alone may drive it, and only while their raw-write
    binding stands.
    \f
    Args:
        session_id: The session being committed.
        body: The declared manifest digest and the descriptive metadata.
        if_match: The caller's ``If-Match`` header.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        drive: The caller's resolved standing on the session.
        ingest: The wired ingest service.

    Returns:
        The committed revision's view.
    """
    metadata = body.metadata.model_dump(exclude_none=True)
    claim = IdempotencyClaim(
        principal=drive.principal.subject,
        key=idempotency_key,
        request_sha256=request_sha256(
            "revision", str(session_id), body.manifest_sha256, content_identity(metadata)
        ),
    )
    record = await ingest.commit(
        drive.ledger.id,
        expected_etag=expected_version(if_match),
        manifest_sha256=body.manifest_sha256,
        metadata=metadata,
        claim=claim,
    )
    return RevisionView.model_validate(record)
