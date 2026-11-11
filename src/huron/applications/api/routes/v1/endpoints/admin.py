"""Platform administration: signing keys and the blocked commit request of a collection."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import RuntimeDep, UploadsDep
from huron.applications.api.routes.v1.schema.admin import SigningKeyOut
from huron.applications.api.routes.v1.schema.files import CommitRequestOut, ResolutionIn
from huron.core.lake.publications.models import CommitState
from huron.core.security.broker import SigningKey

__all__ = ["router"]

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/signing-keys")
async def list_signing_keys(actor: ActorDep, runtime: RuntimeDep) -> list[SigningKeyOut]:
    """Every signing key, newest first, without private parts."""
    return [_out(key) for key in await runtime.lake.keys.list(actor)]


@router.post("/signing-keys/rotate", status_code=status.HTTP_201_CREATED)
async def rotate_signing_key(actor: ActorDep, runtime: RuntimeDep) -> SigningKeyOut:
    """Add a new current key; the previous one keeps verifying for the overlap."""
    key = await runtime.lake.keys.rotate(actor)
    await runtime.ring(refresh=True)
    return _out(key)


@router.post("/collections/{collection_id}/pending-request")
async def resolve_pending_request(
    collection_id: uuid.UUID,
    body: ResolutionIn,
    actor: ActorDep,
    runtime: RuntimeDep,
    orchestration: UploadsDep,
) -> CommitRequestOut:
    """Retry or abandon the blocked commit request of a collection; for a platform admin.

    The route names the collection, reads its pending request, and locks the collection before
    the request. Another user gets 403 first; a process that is not the writer then gets 503.
    ``retry`` makes the request ``accepted`` and starts its publication again. ``abandon`` is
    possible only when no entry of the request is done: the request becomes ``abandoned``, the
    collection is free and the uploads are ``ready`` again.
    """
    await runtime.publications.check_operator(actor)
    orchestration.require_writer()
    outcome = await runtime.publications.resolve(actor, collection_id, body.resolution)
    if outcome.state is CommitState.ACCEPTED:
        orchestration.materializer.start(outcome)
    return CommitRequestOut.model_validate(outcome.as_dict())


def _out(key: SigningKey) -> SigningKeyOut:
    return SigningKeyOut(
        kid=key.kid, created_at=key.created_at, retired_at=key.retired_at, public_jwk=key.public_jwk
    )
