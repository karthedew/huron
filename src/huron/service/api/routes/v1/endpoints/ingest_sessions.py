"""Ingest sessions: open one, read it, keep its lease alive, or give it up.

Two routers open a session - on an existing raw dataset, or by minting one
at intake - and a third addresses a session already open by id. Every
session-view response carries the session's current ``etag`` as its
``ETag`` header, the value a later ``/commit`` names in ``If-Match``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from huron.pkg.auth import Principal
from huron.pkg.catalog import ManifestEntry, validate_manifest
from huron.service.api.authorization import (
    CurrentVisibility,
    IngestDrive,
    dataset_raw_writer,
    project_intake,
    session_overseer,
    session_owner,
)
from huron.service.api.ingest import IngestService
from huron.service.api.problems import problem_response
from huron.service.api.records import Dataset
from huron.service.api.repository import request_sha256
from huron.service.api.routes.v1.preconditions import IdempotencyHeader
from huron.service.api.routes.v1.schema.ingest_sessions import (
    CreateIngestSession,
    CreateIngestSessionInProject,
    IngestSessionView,
    ManifestFile,
)
from huron.service.api.runtime import Ingest, Repository
from huron.service.api.stores import IdempotencyClaim

dataset_ingest_sessions = APIRouter(
    prefix="/datasets/{dataset_id}/ingest-sessions", tags=["ingest-sessions"]
)
project_ingest_sessions = APIRouter(
    prefix="/projects/{project_id}/ingest-sessions", tags=["ingest-sessions"]
)
router = APIRouter(prefix="/ingest-sessions", tags=["ingest-sessions"])

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


def _session_claim(
    principal: str, key: str, dataset_id: UUID, entries: tuple[ManifestEntry, ...]
) -> IdempotencyClaim:
    """Build the idempotency claim a session's opening stakes.

    The claim's digest is the validated manifest's content identity, not
    the raw declared order, so two requests differing only in the order
    they list the same files replay as one session rather than two.

    Args:
        principal: The caller's subject, the claim's principal.
        key: The caller's ``Idempotency-Key`` header.
        dataset_id: The dataset the session is opening against.
        entries: The declared files, to be validated for their identity.

    Returns:
        The claim ``IngestService.create`` stakes in its own transaction.
    """
    manifest = validate_manifest(entries)
    return IdempotencyClaim(
        principal=principal,
        key=key,
        request_sha256=request_sha256("ingest_session", str(dataset_id), manifest.sha256),
    )


async def _open_session(
    ingest: IngestService,
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
    claim = _session_claim(actor, idempotency_key, dataset.id, entries)
    ledger = await ingest.create(dataset, files=entries, created_by=actor, claim=claim)
    response.headers["ETag"] = f'"{ledger.etag}"'
    return IngestSessionView.model_validate(ledger)


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
    entry layer must be ``raw``. Plans every declared file against the
    dataset's latest committed revision - unchanged files are hard-linked,
    everything else must be uploaded - and locks the dataset until the
    session reaches a terminal state. Replaying the same
    ``Idempotency-Key`` with the same files returns the original session
    instead of a 409; reusing the key for a different manifest is refused.
    \f
    Args:
        dataset_id: The dataset the revision will belong to.
        body: The files the revision will hold.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.
        ingest: The wired ingest service.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.
        actor: The caller, whose subject scopes the idempotency claim.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The new session's view, in state UPLOADING.
    """
    dataset = await repository.dataset(dataset_id, visibility)
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
        repository: The wired hierarchy repository.
        ingest: The wired ingest service.
        visibility: The caller's discovery rights, used to resolve
            ``project_id``.
        actor: The caller, whose subject scopes both idempotency claims.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The new session's view, in state UPLOADING.
    """
    dataset_claim = IdempotencyClaim(
        principal=actor.subject,
        key=f"{idempotency_key}/dataset",
        request_sha256=request_sha256(
            "dataset",
            str(project_id),
            body.dataset.slug,
            body.dataset.title,
            body.dataset.description,
            body.dataset.profile_name,
            body.dataset.profile_version,
        ),
    )
    dataset = await repository.create_dataset(
        project_id,
        visibility,
        slug=body.dataset.slug,
        title=body.dataset.title,
        description=body.dataset.description,
        profile_name=body.dataset.profile_name,
        profile_version=body.dataset.profile_version,
        entry_layer="raw",
        claim=dataset_claim,
    )
    return await _open_session(
        ingest,
        dataset,
        body.files,
        actor=actor.subject,
        idempotency_key=idempotency_key,
        response=response,
    )


@router.get("/{session_id}", responses={404: problem_response("no such ingest session")})
async def get_ingest_session(
    drive: Annotated[IngestDrive, Depends(session_overseer)], response: Response
) -> IngestSessionView:
    """Fetch one ingest session and its ledger.

    The owner, or a project admin, may read a session; anyone else, and
    an id that is absent or whose dataset is not discoverable, is 404.
    \f
    Args:
        drive: The caller's resolved standing on the session.
        response: The response the session's ``ETag`` is set on.

    Returns:
        The session's current view.
    """
    response.headers["ETag"] = f'"{drive.ledger.etag}"'
    return IngestSessionView.model_validate(drive.ledger)


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
    ledger = await ingest.heartbeat(drive.ledger.session)
    response.headers["ETag"] = f'"{ledger.etag}"'
    return IngestSessionView.model_validate(ledger)


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
    ledger = await ingest.abort(drive.ledger, actor=drive.principal.subject, forced=not drive.owner)
    response.headers["ETag"] = f'"{ledger.etag}"'
    return IngestSessionView.model_validate(ledger)
