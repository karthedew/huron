"""Token exchange and identity bodies."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["ExchangeIn", "ExchangeOut", "RoleOut", "WhoAmI"]


class ExchangeIn(BaseModel):
    """A company ID token to exchange."""

    company_token: str = Field(min_length=1)


class ExchangeOut(BaseModel):
    """A Huron token and who it names."""

    huron_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    subject: str
    name: str
    groups: list[str]


class RoleOut(BaseModel):
    """One role the caller holds."""

    scope: str
    scope_id: str | None
    role: str


class WhoAmI(BaseModel):
    """The caller, their groups and their effective roles."""

    subject: str
    name: str
    groups: list[str]
    roles: list[RoleOut]
