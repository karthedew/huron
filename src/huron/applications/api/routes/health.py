"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from huron.applications.api.dependencies import RuntimeDep
from huron.applications.api.routes.v1.schema.common import Health
from huron.applications.api.runtime import VERSION

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(runtime: RuntimeDep) -> Health:
    """The service is up; reports the instance the share marker must name."""
    return Health(status="ok", instance_id=str(runtime.settings.instance_id), version=VERSION)


@router.get("/readyz")
async def readyz(runtime: RuntimeDep) -> JSONResponse:
    """The database and the key ring are usable."""
    checks = await runtime.ready()
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not ready", "checks": checks},
        status_code=200 if ready else 503,
    )
