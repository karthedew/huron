"""Request and response bodies owned by ``endpoints/users.py`` (human identities)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserView(BaseModel):
    """One human identity, as the API publishes them.

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
