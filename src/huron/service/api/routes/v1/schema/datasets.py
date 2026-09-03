"""Request and response bodies owned by ``endpoints/datasets.py``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from huron.pkg.catalog.layers import Layer


class CreateDataset(BaseModel):
    """The body of ``POST /projects/{project_id}/datasets``.

    ``slug`` is the dataset's permanent name within its project - unique
    there, immutable afterwards, and checked against the catalog's slug
    rules. A profile (``profile_name`` and ``profile_version``) is required
    of every dataset; ``entry_layer`` declares where its data first
    arrives. A dataset is ``ACTIVE`` from the moment it is created.
    """

    slug: str
    title: str = Field(min_length=1)
    description: str = ""
    profile_name: str
    profile_version: str
    #: Where this dataset's data first arrives. "raw" is the default and the
    #: common case; "bronze" or "silver" declares that the lake is not the
    #: origin of these bytes (a streaming feed, an instrument, published
    #: reference data), so no raw revision will ever exist. "gold" is refused:
    #: a product version without a derivation record is not a product.
    entry_layer: Literal["raw", "bronze", "silver"] = "raw"


class PatchDataset(BaseModel):
    """The body of ``PATCH /datasets/{dataset_id}``: the fields a caller may change.

    A field left out or sent as ``null`` keeps its value. ``slug`` is
    accepted only so that an attempted change is refused explicitly, with
    ``SLUG_IMMUTABLE``, rather than silently ignored; sending the current
    slug is harmless. The patch is applied only against the version the
    ``If-Match`` header names.
    """

    slug: str | None = None
    title: str | None = None
    description: str | None = None


class CreateRelease(BaseModel):
    """The body of ``POST /datasets/{dataset_id}/releases``: pin a tag to a revision.

    ``tag`` must be new for the dataset and follow the catalog's tag rules;
    ``revision_number`` must name a revision the dataset already has. Once
    created, the tag resolves to that revision forever; it is never
    repointed.
    """

    tag: str
    revision_number: int = Field(ge=1, le=999_999)
    title: str | None = None


class DatasetView(BaseModel):
    """One dataset as the API publishes it.

    ``version`` is the value ``If-Match`` carries back on a PATCH; the
    raw-store generation behind it is not part of this contract.
    ``lifecycle_state`` is the dataset's ``DatasetLifecycle`` name and
    ``entry_layer`` the layer its data first arrives in.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    slug: str
    title: str
    description: str
    profile_name: str
    profile_version: str
    entry_layer: Layer
    lifecycle_state: str
    version: int
    created_at: datetime


class ReleaseView(BaseModel):
    """One release tag, resolving to exactly one revision, forever."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    tag: str
    revision_id: UUID
    revision_number: int
    title: str | None
    created_by: str
    created_at: datetime


class LayerCapabilities(BaseModel):
    """What the calling principal may do in one layer of one dataset."""

    read: bool
    write: bool


class LayerView(BaseModel):
    """One layer of the workflow, annotated with what the caller may do there."""

    layer: Layer
    derived_from: list[Layer]
    principal_writable: bool
    accepts_direct_entry: bool
    is_entry_layer: bool
    produced_by: str
    caller_may: LayerCapabilities


class WriteIntent(BaseModel):
    """An authorization to commit to one layer, granted and not yet used."""

    dataset_id: UUID
    layer: Layer
    granted_to: str
    principal_kind: str
    capability: str
