"""Request and response bodies owned by ``endpoints/users.py`` (admin-provisioned users)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateUser(BaseModel):
    """The body of ``POST /users``: provision a human who signs in with a password.

    ``username`` becomes the principal's subject - lowercase, two to
    sixty-three characters - and must be held by no principal at all,
    password or OIDC, enabled or disabled; a taken name is refused with
    ``USERNAME_TAKEN`` rather than silently attaching a password to an
    existing identity. ``password`` is set exactly once here; afterwards
    only an administrator's ``SetPassword`` replaces it.
    """

    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,62}$")
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=12)


class SetPassword(BaseModel):
    """The body of ``PUT /users/{principal_id}/password``: the replacement password.

    There are no reset tokens and no self-service change by design: an
    administrator sets the new password, and every session the user held
    is revoked when it takes effect.
    """

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
    """The acknowledgement of a password reset.

    Every session the user held was revoked before this was returned, so
    ``status`` (always ``password-reset``) also means "signed out
    everywhere".
    """

    status: Literal["password-reset"]
