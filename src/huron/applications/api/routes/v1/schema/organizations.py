"""Request and response bodies owned by ``endpoints/organizations.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from huron.applications.api.routes.v1.schema.descriptions import DescriptionPatch


class CreateOrganization(BaseModel):
    """The body of ``POST /organizations``.

    ``slug`` is the organization's permanent name: unique across the
    platform, immutable afterwards, and checked against the catalog's slug
    rules and its reserved root names. ``description`` may be left empty.
    """

    slug: str
    title: str = Field(min_length=1)
    description: str = ""


class PatchOrganization(DescriptionPatch):
    """The body of ``PATCH /organizations/{organization_id}``: the changeable fields.

    A field left out or sent as ``null`` keeps its value; the patch is
    applied only against the version the ``If-Match`` header names.
    """


class OrganizationView(BaseModel):
    """One organization as the API publishes it.

    ``version`` is the value ``If-Match`` carries back on a PATCH; the
    raw-store ``generation`` behind it is not part of this contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    title: str
    description: str
    version: int
    created_at: datetime
