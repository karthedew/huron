"""Request bodies owned by ``endpoints/datasets.py``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
