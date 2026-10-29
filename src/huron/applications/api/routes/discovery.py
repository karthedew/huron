"""OIDC discovery and JWKS for systems that trust Huron tokens."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from huron.applications.api.dependencies import RuntimeDep
from huron.core.security.broker import discovery_document

__all__ = ["router"]

router = APIRouter(tags=["discovery"])


@router.get("/.well-known/openid-configuration")
async def openid_configuration(runtime: RuntimeDep) -> dict[str, Any]:
    """The issuer's discovery document."""
    return discovery_document(runtime.settings.issuer)


@router.get("/jwks.json")
async def jwks(runtime: RuntimeDep) -> dict[str, Any]:
    """The public keys that verify Huron tokens."""
    return (await runtime.ring()).jwks()
