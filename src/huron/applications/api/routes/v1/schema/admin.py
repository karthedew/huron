"""Audit and signing-key bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

__all__ = ["AuditOut", "SigningKeyOut"]


class AuditOut(BaseModel):
    """One audit entry."""

    id: int | None
    at: datetime
    actor: str
    action: str
    object_type: str
    object_id: str | None
    catalog_id: str | None
    organization_id: str | None
    detail: dict[str, Any]


class SigningKeyOut(BaseModel):
    """A signing key without its private part."""

    kid: str
    created_at: datetime
    retired_at: datetime | None
    public_jwk: dict[str, Any]
