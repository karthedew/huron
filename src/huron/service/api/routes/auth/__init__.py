"""Unversioned authentication routes: login, OIDC, and session introspection.

Mounted at ``/auth`` with no API version prefix (see ``app.py``) - login is
a protocol surface negotiated with browsers and identity providers, whose
redirect URLs live in IdP configuration, not a resource that versions
alongside the rest of the API.
"""

from __future__ import annotations

from fastapi import APIRouter

from .endpoints import login, oidc, session

router = APIRouter()
router.include_router(login.router)
router.include_router(oidc.router)
router.include_router(session.router)

__all__ = ["router"]
