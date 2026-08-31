"""Request bodies owned by ``endpoints/users.py`` (admin-provisioned users)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateUser(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=12)


class SetPassword(BaseModel):
    password: str = Field(min_length=12)
