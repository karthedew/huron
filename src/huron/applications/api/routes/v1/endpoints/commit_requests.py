"""Commit requests: the saved state of a request, for the user who sent it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import RuntimeDep
from huron.applications.api.routes.v1.schema.files import CommitRequestOut

__all__ = ["router"]

router = APIRouter(prefix="/commit-requests", tags=["files"])


@router.get("/{request_id}")
async def get_commit_request(
    request_id: uuid.UUID, actor: ActorDep, runtime: RuntimeDep
) -> CommitRequestOut:
    """The saved state of the caller's commit request; another user's request is not found."""
    outcome = await runtime.publications.status(actor, request_id)
    return CommitRequestOut.model_validate(outcome.as_dict())
