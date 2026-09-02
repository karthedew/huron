"""Request and response bodies owned by ``endpoints/api_keys.py``.

``CreateApiKey`` is also imported by ``endpoints/service_accounts.py`` to
mint keys for service accounts - the only cross-module schema import in the
v1 surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateApiKey(BaseModel):
    name: str = Field(min_length=1)
    scopes: set[str] = Field(default_factory=lambda: {"read"})
    project_id: str | None = None
    expires_in_days: int = Field(default=90, ge=1, le=400)


class IssuedApiKey(BaseModel):
    """A key at the one moment its secret exists in cleartext.

    ``secret`` is returned by this response and by nothing else in the
    service: it is never stored, never logged, and cannot be re-read. A
    caller that loses it issues another key.
    """

    id: str
    name: str
    scopes: list[str]
    expires_at: datetime
    secret: str
