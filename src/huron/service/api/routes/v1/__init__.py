"""The v1 router: every endpoint module aggregated under one prefix.

The credential requirement is declared here, once, rather than on each
path operation: a route reachable under ``/api/v1`` without one is not a
route an author can write by omission.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from huron.service.api.authorization import current_principal
from huron.service.api.problems import AUTHENTICATED_ERRORS

from .endpoints import (
    api_keys,
    bindings,
    datasets,
    organizations,
    policies,
    projects,
    roles,
    search,
    service_accounts,
    users,
)

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(current_principal)],
    responses=AUTHENTICATED_ERRORS,
)
router.include_router(organizations.router)
router.include_router(projects.organization_projects)
router.include_router(projects.router)
router.include_router(datasets.project_datasets)
router.include_router(datasets.router)
router.include_router(roles.router)
router.include_router(bindings.router)
router.include_router(bindings.organization_bindings)
router.include_router(bindings.project_bindings)
router.include_router(bindings.dataset_bindings)
router.include_router(service_accounts.router)
router.include_router(policies.router)
router.include_router(policies.organization_attachments)
router.include_router(policies.project_attachments)
router.include_router(policies.dataset_attachments)
router.include_router(api_keys.router)
router.include_router(users.router)
router.include_router(search.router)

__all__ = ["router"]
