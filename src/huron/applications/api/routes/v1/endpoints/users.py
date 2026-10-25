"""Authorized disablement of human identities and their API keys."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import require_system
from huron.applications.api.dependencies import Identity
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.schema.users import (
    UserView,
)

_manage_users = require_system("user.manage")
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(_manage_users)])


@router.post(
    "/{principal_id}/disable",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def disable_user(principal_id: UUID, identity: Identity) -> UserView:
    """Disable a user and revoke every API key they hold.

    Requires ``user.manage`` at SYSTEM scope. A disabled user can no longer
    authenticate with a revoked API key, and the API offers no way to re-enable
    their identity. An unknown principal is 404;
    one that is a service account rather than a user is refused with 409.
    \f
    Args:
        principal_id: The user to disable.
        identity: The actor-bound identity service.

    Returns:
        The user as the API renders it, with ``disabled_at`` set.

    """
    return UserView.model_validate(await identity.disable_user(principal_id))
