"""Request and response bodies owned by ``endpoints/datasets.py``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from huron.pkg.catalog.layers import Layer


class CreateDataset(BaseModel):
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
    slug: str | None = None
    title: str | None = None
    description: str | None = None


class CreateRelease(BaseModel):
    tag: str
    revision_number: int = Field(ge=1, le=999_999)
    title: str | None = None


class DatasetView(BaseModel):
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
