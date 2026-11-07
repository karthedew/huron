"""Liveness and readiness."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from huron.applications.api.dependencies import RuntimeDep
from huron.applications.api.routes.v1.schema.common import Health, ServiceUser
from huron.applications.api.runtime import VERSION
from huron.applications.api.settings import Settings

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(runtime: RuntimeDep) -> Health:
    """The service is up; reports the instance the share marker must name and the uploads."""
    settings = runtime.settings
    return Health(
        status="ok",
        instance_id=str(settings.instance_id),
        version=VERSION,
        organizations_managed=settings.declarations.managed,
        uploads_url=settings.uploads_url,
        service_user=_service_user(settings),
        upload_hook_timeout=int(settings.upload_hook_timeout.total_seconds()),
    )


@router.get("/readyz")
async def readyz(runtime: RuntimeDep) -> JSONResponse:
    """The database, the key ring and, with a lake, the upload directory are usable."""
    checks = await runtime.ready()
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not ready", "checks": checks},
        status_code=200 if ready else 503,
    )


def _service_user(settings: Settings) -> ServiceUser | None:
    group = settings.service_group
    if group is None:
        return None
    # The primary group is the pod's runAsGroup, not a setting.
    return ServiceUser(uid=settings.service_uid, gid=os.getgid(), group=group)
