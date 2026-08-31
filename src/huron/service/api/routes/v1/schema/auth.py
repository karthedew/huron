"""Request bodies owned by ``endpoints/auth.py``.

``CreateApiKey`` is also imported by ``endpoints/rbac.py`` to mint keys for
service accounts - the only cross-module schema import in the v1 surface.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateApiKey(BaseModel):
    name: str = Field(min_length=1)
    scopes: set[str] = Field(default_factory=lambda: {"read"})
    project_id: str | None = None
    expires_in_days: int = Field(default=90, ge=1, le=400)
