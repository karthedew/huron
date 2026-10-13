"""Dedicated signed-BFF transport for existing Raw upload and revision operations."""

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from huron.applications.api.problems import AUTHENTICATED_ERRORS, problem_response
from huron.applications.api.raw_web import Delegation, Operations
from huron.applications.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.applications.api.routes.v1.schema.ingest_sessions import (
    CommitIngestSession,
    IngestFileView,
    IngestSessionView,
    ManifestFile,
)
from huron.applications.api.routes.v1.schema.revisions import RevisionView
from huron.applications.api.streams import body_chunks
from huron.core.raw.manifest import ManifestEntry
from huron.core.raw.types import SessionLedger
from huron.core.raw.web import RawWebOperations
from huron.core.raw.web_ports import RawRegistration
from huron.core.security.raw_delegation import DelegationTarget, RawDelegation

router = APIRouter(
    prefix="/api/raw-web",
    tags=["raw-web"],
    responses={
        **AUTHENTICATED_ERRORS,
        400: problem_response("invalid manifest, path, or transfer evidence"),
        404: problem_response("no such authorized Raw target or upload"),
        409: problem_response("upload state or retry identity conflicts"),
        412: problem_response("the upload version changed"),
        413: problem_response("the declared submission exceeds a configured limit"),
    },
)


class CreateUpload(BaseModel):
    """A complete submission; identity comes from the signed target."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    description: str = ""
    files: list[ManifestFile] = Field(max_length=10_000)


class UploadView(IngestSessionView):
    """The real Raw ledger with its verified external target and publication status."""

    target: DelegationTarget
    registration: RawRegistration | None


class CommitView(RevisionView):
    """A durable immutable revision and its separate Polaris publication status."""

    registration: RawRegistration | None


class RegisterRevision(BaseModel):
    """The committed revision whose external registration the BFF verified."""

    model_config = ConfigDict(extra="forbid")
    revision_id: UUID


class RevisionPage(BaseModel):
    """Bounded newest-first revision discovery."""

    revisions: list[RevisionView]
    next_before: int | None


async def _upload_view(
    ledger: SessionLedger,
    operations: RawWebOperations,
    delegation: RawDelegation,
    response: Response,
) -> UploadView:
    """Render the authoritative ledger and its durable registration state.

    Args:
        ledger: Current domain ledger.
        operations: Authorized publication reads.
        delegation: Verified upstream target.
        response: Carries the current ETag.

    Returns:
        The complete upload view.
    """
    response.headers["ETag"] = f'"{ledger.etag}"'
    return UploadView(
        **IngestSessionView.model_validate(ledger).model_dump(),
        target=delegation.target,
        registration=await operations.registration(ledger.id),
    )


@router.post("/uploads", status_code=201)
async def create_upload(
    body: CreateUpload,
    idempotency_key: IdempotencyHeader,
    operations: Operations,
    delegation: Delegation,
    response: Response,
) -> UploadView:
    """Open or resume one complete independent submission.

    Args:
        body: Required descriptive intake and complete file manifest.
        idempotency_key: Stable upload retry identity.
        operations: Target-checked domain workflow.
        delegation: Signed actor and target.
        response: Carries the current ETag.

    Returns:
        The actual persisted upload ledger.
    """
    files = tuple(ManifestEntry(**item.model_dump()) for item in body.files)
    ledger = await operations.create(files, idempotency_key)
    return await _upload_view(ledger, operations, delegation, response)


@router.get("/uploads/{session_id}")
async def upload(
    session_id: UUID,
    operations: Operations,
    delegation: Delegation,
    response: Response,
) -> UploadView:
    """Read the authenticated owner's upload after matching its persisted target.

    Args:
        session_id: Upload identity.
        operations: Target-checked domain workflow.
        delegation: Signed actor and target.
        response: Carries the current ETag.

    Returns:
        The current persisted ledger.
    """
    return await _upload_view(await operations.ledger(session_id), operations, delegation, response)


@router.put("/uploads/{session_id}/files/{file_id}/parts/{part}")
async def receive_upload_part(
    session_id: UUID,
    file_id: UUID,
    part: int,
    request: Request,
    content_length: Annotated[int, Header(alias="Content-Length", ge=0)],
    operations: Operations,
) -> IngestFileView:
    """Stream exactly one signed part with bounded memory.

    Args:
        session_id: Owned upload identity.
        file_id: File within that upload.
        part: One-based part number.
        request: Streaming HTTP body.
        content_length: Exact transfer length.
        operations: Target-checked Raw transfer workflow.

    Returns:
        The real file ledger after the part is verified.
    """
    file = await operations.receive_part(
        session_id,
        file_id,
        part,
        body_chunks(request),
        content_length=content_length,
    )
    return IngestFileView.model_validate(file)


@router.post("/uploads/{session_id}/files/{file_id}/complete")
async def complete_file(session_id: UUID, file_id: UUID, operations: Operations) -> IngestFileView:
    """Complete the actual multipart file and verify its declared checksum.

    Args:
        session_id: Owned upload identity.
        file_id: File within that upload.
        operations: Target-checked Raw workflow.

    Returns:
        The complete verified file ledger.
    """
    return IngestFileView.model_validate(await operations.complete_file(session_id, file_id))


@router.post("/uploads/{session_id}/commit", status_code=201)
async def commit_upload(
    session_id: UUID,
    body: CommitIngestSession,
    if_match: IfMatchHeader,
    idempotency_key: IdempotencyHeader,
    operations: Operations,
) -> CommitView:
    """Publish one immutable revision and preserve pending catalog registration for retry.

    Args:
        session_id: Owned verified upload identity.
        body: Manifest identity and required metadata.
        if_match: Last observed session version.
        idempotency_key: Stable commit identity.
        operations: Target-checked Raw publication workflow.

    Returns:
        The actual committed revision and registration state.
    """
    record = await operations.commit(
        session_id,
        expected_etag=expected_version(if_match),
        key=idempotency_key,
        manifest_sha256=body.manifest_sha256,
        metadata=body.metadata.model_dump(exclude_none=True),
    )
    return CommitView(
        **RevisionView.model_validate(record).model_dump(),
        registration=await operations.registration(session_id),
    )


@router.post("/uploads/{session_id}/registration")
async def acknowledge_registration(
    session_id: UUID,
    body: RegisterRevision,
    operations: Operations,
) -> RawRegistration | None:
    """Retain the trusted BFF's acknowledgement of this revision's Polaris registration.

    Args:
        session_id: Owned committed upload identity.
        body: Exact registered revision identity.
        operations: Target-checked publication workflow.

    Returns:
        The durable registration receipt.
    """
    return await operations.registration(session_id, acknowledge=body.revision_id)


@router.post("/uploads/{session_id}/{action}")
async def advance_upload(
    session_id: UUID,
    action: Literal["heartbeat", "verify", "abort"],
    operations: Operations,
    delegation: Delegation,
    response: Response,
) -> UploadView:
    """Execute an authorized lease, verification or abort transition.

    Args:
        session_id: Owned upload identity.
        action: Requested transition.
        operations: Target-checked Raw workflow.
        delegation: Signed actor and target.
        response: Carries the current ETag.

    Returns:
        The resulting real upload ledger.
    """
    ledger = await operations.advance(session_id, action)
    return await _upload_view(ledger, operations, delegation, response)


@router.get("/datasets/{dataset_id}/revisions")
async def list_revisions(
    dataset_id: UUID,
    operations: Operations,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> RevisionPage:
    """Page the selected dataset's actual immutable revisions.

    Args:
        dataset_id: Opaque backend identity matched to the signed target.
        operations: Target-checked revision workflow.
        before: Exclusive revision-number cursor.

    Returns:
        At most 100 revisions and a continuation cursor.
    """
    records = await operations.revisions(dataset_id, before=before)
    page = records[:100]
    return RevisionPage(
        revisions=[RevisionView.model_validate(item) for item in page],
        next_before=page[-1].number if len(records) > 100 else None,
    )


@router.get("/revisions/{revision_id}/manifest")
async def manifest(revision_id: UUID, operations: Operations) -> FileResponse:
    """Serve the stored manifest only after current target and read authorization.

    Args:
        revision_id: Requested immutable revision.
        operations: Target-checked Raw reader.

    Returns:
        The real stored manifest document.
    """
    path, stat = await operations.manifest(revision_id)
    record = await operations.revision(revision_id)
    return FileResponse(
        path,
        stat_result=stat,
        media_type="application/json",
        headers={"ETag": f'"{record.manifest_sha256}"'},
    )


@router.get("/revisions/{revision_id}/files/{path:path}")
async def payload(revision_id: UUID, path: str, operations: Operations) -> FileResponse:
    """Serve only manifest-listed payload bytes with Range support.

    Args:
        revision_id: Requested immutable revision.
        path: Manifest-relative payload path.
        operations: Target-checked Raw reader.

    Returns:
        The real verified payload file.
    """
    file = await operations.payload(revision_id, path)
    return FileResponse(
        file.location,
        stat_result=file.stat,
        media_type=file.entry.media_type,
        filename=PurePosixPath(file.entry.path).name,
        headers={"ETag": f'"{file.entry.sha256}"'},
    )


@router.get("/revisions/{revision_id}")
async def revision(revision_id: UUID, operations: Operations) -> RevisionView:
    """Read one exact revision after matching its mapped target.

    Args:
        revision_id: Requested immutable revision.
        operations: Target-checked Raw reader.

    Returns:
        The actual committed revision record.
    """
    return RevisionView.model_validate(await operations.revision(revision_id))
