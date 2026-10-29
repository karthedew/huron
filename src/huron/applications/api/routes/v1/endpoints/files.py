"""Recorded files and commits."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Response

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import LakeDep
from huron.applications.api.routes.pagination import Cursor, Limit
from huron.applications.api.routes.preconditions import set_etag
from huron.applications.api.routes.v1.schema.common import Page, page_of
from huron.applications.api.routes.v1.schema.files import CommitOut, CommitResultOut, FileOut
from huron.core.lake.files.commits import parse_commit_request

__all__ = ["router"]

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


@router.post("/commits")
async def commit(
    collection_id: uuid.UUID,
    actor: ActorDep,
    lake: LakeDep,
    response: Response,
    body: Annotated[dict[str, Any], Body()],
) -> CommitResultOut:
    """Record added and removed files in one transaction, or refuse the whole commit."""
    result = await lake.commits.commit(actor, collection_id, parse_commit_request(body))
    set_etag(response, result.version)
    return CommitResultOut.model_validate(result.as_dict())


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
