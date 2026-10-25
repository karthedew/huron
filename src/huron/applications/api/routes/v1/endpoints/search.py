"""Catalog search.

Authorization is doubled up by design: this router requires a credential
like every other v1 route, and once the projection exists, results are
re-authorized per item before serialization - the credential check here
only proves the caller is someone, not what they may see.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter

from huron.applications.api.problems import problem_response
from huron.core.hierarchy.errors import ProjectionUnavailable

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    response_model=None,
    responses={503: problem_response("the search projection is not configured")},
)
async def search_unavailable() -> NoReturn:
    """Search the catalog.

    The search projection is not configured, so every request is refused
    with 503 ``PROJECTION_UNAVAILABLE``.
    \f
    Raises:
        ProjectionUnavailable: Always, because no search projection is
            configured.
    """
    raise ProjectionUnavailable("search projection is not configured")
