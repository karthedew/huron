"""Reading a committed revision: its record, its manifest and its payload files.

Fetching the revision itself needs only a credential and the caller's
visibility; downloading its manifest or a payload file re-authorizes on
every request against ``data.read@raw`` at the revision's dataset scope.
Only a path the stored manifest lists is ever served - nothing under a
revision's private staging is reachable through these routes.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from huron.service.api.authorization import CurrentVisibility, RevisionRead, revision_raw_reader
from huron.service.api.problems import problem_response
from huron.service.api.routes.v1.schema.revisions import RevisionView
from huron.service.api.runtime import Revisions

router = APIRouter(prefix="/revisions", tags=["revisions"])


@router.get(
    "/{revision_id}",
    responses={404: problem_response("no such revision, or its dataset is not visible")},
)
async def get_revision(
    revision_id: UUID, revisions: Revisions, visibility: CurrentVisibility
) -> RevisionView:
    """Fetch one committed revision by id.

    An id that names no revision, or one whose dataset the caller cannot
    discover, is 404.
    \f
    Args:
        revision_id: The revision to fetch.
        revisions: The wired revision service.
        visibility: The caller's discovery rights.

    Returns:
        The revision as the API renders it.
    """
    record = await revisions.revision(revision_id, visibility)
    return RevisionView.model_validate(record)


@router.get(
    "/{revision_id}/manifest",
    responses={404: problem_response("no such revision, or its dataset is not visible")},
)
async def get_revision_manifest(
    read: Annotated[RevisionRead, Depends(revision_raw_reader)], revisions: Revisions
) -> FileResponse:
    """Download the revision's stored manifest document.

    Re-authorized against ``data.read@raw`` on every request; supports
    ``Range`` for a resumable download.
    \f
    Args:
        read: The caller's resolved standing on the revision.
        revisions: The wired revision service.

    Returns:
        The stored ``manifest.json`` bytes, with its content identity as a
        strong ``ETag``.
    """
    location, stat = await revisions.manifest_file(read.record)
    return FileResponse(
        location,
        media_type="application/json",
        stat_result=stat,
        headers={"ETag": f'"{read.record.manifest_sha256}"'},
    )


@router.get(
    "/{revision_id}/files/{path:path}",
    responses={
        400: problem_response("the path breaks a storage-layout rule"),
        404: problem_response(
            "no such revision, its dataset is not visible, or the manifest lists no such path"
        ),
    },
)
async def get_revision_file(
    path: str, read: Annotated[RevisionRead, Depends(revision_raw_reader)], revisions: Revisions
) -> FileResponse:
    """Download one file of a revision's payload.

    Only a path the stored manifest lists is served; re-authorized against
    ``data.read@raw`` on every request; supports ``Range`` for a resumable
    download.
    \f
    Args:
        path: The file's manifest path, exactly as declared.
        read: The caller's resolved standing on the revision.
        revisions: The wired revision service.

    Returns:
        The file's bytes, with its content identity as a strong ``ETag``
        and, for a non-ASCII name, an RFC 5987 ``Content-Disposition``.
    """
    payload = await revisions.payload_file(read.record, path)
    return FileResponse(
        payload.location,
        media_type=payload.entry.media_type,
        filename=PurePosixPath(payload.entry.path).name,
        stat_result=payload.stat,
        headers={"ETag": f'"{payload.entry.sha256}"'},
    )
