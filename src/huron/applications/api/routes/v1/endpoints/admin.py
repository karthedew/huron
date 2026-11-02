"""Signing-key administration."""

from __future__ import annotations

from fastapi import APIRouter, status

from huron.applications.api.authorization import ActorDep
from huron.applications.api.dependencies import RuntimeDep
from huron.applications.api.routes.v1.schema.admin import SigningKeyOut
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


def _out(key: SigningKey) -> SigningKeyOut:
    return SigningKeyOut(
        kid=key.kid, created_at=key.created_at, retired_at=key.retired_at, public_jwk=key.public_jwk
    )
