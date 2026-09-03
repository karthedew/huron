"""Request and response bodies owned by ``endpoints/projects.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateProject(BaseModel):
    """The body of ``POST /organizations/{organization_id}/projects``.

    ``slug`` is the project's permanent name within its organization -
    unique there, immutable afterwards, and checked against the catalog's
    slug rules. ``data_classification`` must be a code from the
    deployment's configured classification vocabulary; any other value is
    refused with ``CLASSIFICATION_UNKNOWN``.
    """

    slug: str
    title: str = Field(min_length=1)
    description: str = ""
    data_classification: str


class PatchProject(BaseModel):
    """The body of ``PATCH /projects/{project_id}``: the changeable fields.

    A field left out or sent as ``null`` keeps its value; the patch is
    applied only against the version the ``If-Match`` header names. The
    classification is fixed at creation and is not part of this body.
    """

    #: Accepted only so an attempted change is refused explicitly; slugs are
    #: immutable at every level, for everyone.
    slug: str | None = None
    title: str | None = None
    description: str | None = None


class ProjectView(BaseModel):
    """One project as the API publishes it.

    ``version`` is the value ``If-Match`` carries back on a PATCH; the
    raw-store generation behind it is not part of this contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    slug: str
    title: str
    description: str
    data_classification: str
    version: int
    created_at: datetime
