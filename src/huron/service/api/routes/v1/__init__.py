"""The v1 router: every endpoint module aggregated under one prefix."""

from __future__ import annotations

from fastapi import APIRouter

from .endpoints import auth, datasets, organizations, policies, projects, rbac, users

router = APIRouter()
router.include_router(organizations.router, tags=["organizations"])
router.include_router(projects.router, tags=["projects"])
router.include_router(datasets.router, tags=["datasets"])
router.include_router(rbac.router, tags=["rbac"])
router.include_router(policies.router, tags=["policies"])
router.include_router(auth.router, tags=["auth"])
router.include_router(users.router, tags=["users"])

__all__ = ["router"]
