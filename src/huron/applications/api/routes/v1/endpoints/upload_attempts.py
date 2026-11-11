"""Upload attempts: the owner reads an attempt, and the read seals a complete upload."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import RuntimeDep, UploadsDep
from huron.applications.api.disk import SEAL_WAIT
from huron.applications.api.routes.v1.schema.uploads import UploadAttemptOut
from huron.core.lake.uploads.models import AttemptState

__all__ = ["router"]

router = APIRouter(prefix="/upload-attempts", tags=["uploads"])

_UNSEALED = frozenset({AttemptState.RECEIVING, AttemptState.SEALING})


@router.get("/{attempt_id}")
async def get_upload_attempt(
    attempt_id: uuid.UUID, actor: ActorDep, runtime: RuntimeDep, orchestration: UploadsDep
) -> UploadAttemptOut:
    """The caller's upload attempt: its state and its current upload ID.

    Another user's attempt is not found. In the writer, the read first runs the API's own seal
    check of a ``receiving`` or ``sealing`` attempt: a complete upload that no hook reported is
    sealed, and the read waits at most 20 seconds for the seal. A process that serves reads
    only answers from the database and starts no seal.
    """
    attempt = await runtime.attempts.get(actor, attempt_id)
    if orchestration.ownership.writable and attempt.state in _UNSEALED:
        await orchestration.sealing.settle([attempt.current_upload_id], SEAL_WAIT)
        attempt = await runtime.attempts.get(actor, attempt_id)
    return UploadAttemptOut.model_validate(attempt.as_dict())
