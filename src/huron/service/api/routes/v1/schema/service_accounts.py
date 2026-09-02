"""Request and response bodies owned by ``endpoints/service_accounts.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from huron.service.api.routes.v1.schema.api_keys import IssuedApiKey


class CreateServiceAccount(BaseModel):
    name: str = Field(min_length=2, max_length=62)


class ServiceAccountView(BaseModel):
    """A roleless identity owned by one organization.

    ``subject`` is the identity its API keys authenticate as; ``name`` is
    unique within the owning organization and is what the collection is
    ordered by. ``disabled_at`` set means every key it holds has been
    revoked.
    """

    model_config = ConfigDict(from_attributes=True)

    principal_id: UUID
    organization_id: UUID
    name: str
    subject: str
    created_by: str
    created_at: datetime
    disabled_at: datetime | None


class IssuedServiceAccountKey(IssuedApiKey):
    """A key that authenticates AS the service account it names."""

    subject: str
