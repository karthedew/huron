"""Request and response bodies owned by ``endpoints/bindings.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from huron.pkg.rbac import ScopeType

PRINCIPAL_PATTERN = r"^(user|group|sa):.+$"


class CreateRoleBinding(BaseModel):
    """Grant ``role`` to ``principal`` at the scope named by the route."""

    principal: str = Field(pattern=PRINCIPAL_PATTERN)
    role: str = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=400)


class RoleBindingView(BaseModel):
    """One grant of one role to one principal at one scope.

    ``scope_id`` is ``null`` if and only if ``scope_type`` is ``SYSTEM``;
    every other scope names the organization, project or dataset the grant
    was made at. ``expires_at`` is ``null`` for a grant that does not lapse.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    principal: str
    role_code: str
    scope_type: ScopeType
    scope_id: UUID | None
    created_by: str
    created_at: datetime
    expires_at: datetime | None
