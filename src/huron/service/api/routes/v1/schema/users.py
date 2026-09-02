"""Request and response bodies owned by ``endpoints/users.py`` (admin-provisioned users)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateUser(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=12)


class SetPassword(BaseModel):
    password: str = Field(min_length=12)


class UserView(BaseModel):
    """One admin-provisioned human, as the API publishes them.

    The identity provider's subject for this person is not part of this
    contract; neither is ``kind``, which every route returning this model
    has already constrained to a user.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    display_name: str
    disabled_at: datetime | None
    created_at: datetime


class PasswordReset(BaseModel):
    """The acknowledgement of a password reset. Every session the user held
    was revoked before this was returned."""

    status: Literal["password-reset"]
