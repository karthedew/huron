"""Request bodies owned by ``endpoints/rbac.py``."""

from __future__ import annotations

from pydantic import BaseModel, Field

PRINCIPAL_PATTERN = r"^(user|group|sa):.+$"


class CreateRoleBinding(BaseModel):
    """Grant ``role`` to ``principal`` at the scope named by the route."""

    principal: str = Field(pattern=PRINCIPAL_PATTERN)
    role: str = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=400)


class CreateServiceAccount(BaseModel):
    name: str = Field(min_length=2, max_length=62)
