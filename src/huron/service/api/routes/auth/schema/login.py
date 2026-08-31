"""Request body owned by ``endpoints/login.py``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PasswordLogin(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
