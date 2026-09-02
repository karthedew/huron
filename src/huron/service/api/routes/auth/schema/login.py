"""Request and response bodies owned by ``endpoints/login.py``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PasswordLogin(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResult(BaseModel):
    """What a successful password login hands the browser.

    ``csrf_token`` is the double-submit token for this session and is
    returned exactly once, to the caller that just proved the password.
    """

    subject: str
    display_name: str
    csrf_token: str


class SignOut(BaseModel):
    status: Literal["signed-out"]
