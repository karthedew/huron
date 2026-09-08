"""Request and response bodies owned by ``endpoints/login.py``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PasswordLogin(BaseModel):
    """The body of ``POST /auth/login``: a username and the password proving it.

    Both must be non-empty; nothing else is checked here. Whether the pair
    names an enabled user with that password is decided by the login
    route, which answers every failure identically.
    """

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
    """The acknowledgement ``POST /auth/logout`` returns.

    ``status`` is always ``signed-out``: by the time this is sent, the
    session behind the request (if there was one) is revoked and the
    session cookie is cleared.
    """

    status: Literal["signed-out"]
