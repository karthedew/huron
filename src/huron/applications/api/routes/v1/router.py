"""The ``/api/v1`` router."""

from __future__ import annotations

from fastapi import APIRouter

from huron.applications.api.routes.v1.endpoints import (
    admin,
    auth,
    catalogs,
    collections,
    files,
    grants,
    namespaces,
    organizations,
    schemas,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/v1")
for module in (
    auth,
    organizations,
    grants,
    schemas,
    catalogs,
    namespaces,
    collections,
    files,
    admin,
):
    router.include_router(module.router)
