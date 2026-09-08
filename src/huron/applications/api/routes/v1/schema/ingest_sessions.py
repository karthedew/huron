"""Request and response bodies owned by ``endpoints/ingest_sessions.py``.

The views render :class:`huron.core._ingest.SessionLedger` and its
files directly (``model_config = ConfigDict(from_attributes=True)``), so a
handler never re-shapes a response by hand; only ``completed_parts`` needs a
validator, because the domain holds it as a ``frozenset`` and the wire
contract promises an ascending list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from huron.pkg.catalog import FileState, IngestState, UploadAction

from .revisions import MetadataSubmission


class ManifestFile(BaseModel):
    """One declared file: the manifest entry as the client states it."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = "application/octet-stream"


class CreateIngestSession(BaseModel):
    """Body of ``POST /datasets/{dataset_id}/ingest-sessions``: the files the revision will hold.

    Emptiness is refused by the domain as ``EMPTY_REVISION``, not by a
    ``min_length`` here, so the client sees the same code whether the list
    is empty or merely invalid in some other way.
    """

    files: list[ManifestFile]


class NewDataset(BaseModel):
    """The dataset an intake creates before opening its first session.

    Its entry layer is ``raw`` by definition - an intake exists to open a
    raw ingest session - so the body carries no ``entry_layer`` field.
    """

    slug: str
    title: str = Field(min_length=1)
    description: str = ""
    profile_name: str
    profile_version: str


class CreateIngestSessionInProject(BaseModel):
    """Body of ``POST /projects/{project_id}/ingest-sessions``: a dataset to create and its files.

    The intake creates the dataset, always with ``raw`` as its entry
    layer, and opens the first session on it in one request.
    """

    dataset: NewDataset
    files: list[ManifestFile]


class CommitIngestSession(BaseModel):
    """Body of ``…/commit``: the declared identity, restated, and the final descriptive metadata."""

    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: MetadataSubmission


class IngestFileView(BaseModel):
    """One planned file and its progress: the plan and the ledger."""

    model_config = ConfigDict(from_attributes=True)

    file_id: UUID
    path: str
    size: int
    expected_sha256: str
    action: UploadAction
    part_count: int
    state: FileState
    completed_parts: list[int]

    @field_validator("completed_parts", mode="before")
    @classmethod
    def _sorted(cls, value: Any) -> list[int]:
        """Render the domain's ``frozenset`` of parts as an ascending list.

        Args:
            value: The raw ``completed_parts`` value read off the domain
                object, a ``frozenset[int]`` or an already-ordered sequence.

        Returns:
            The same part numbers, sorted ascending.
        """
        return sorted(value)


class IngestSessionView(BaseModel):
    """A session and its ledger; ``etag`` is what ``If-Match`` carries back on commit."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    revision_id: UUID
    revision_number: int
    state: IngestState
    etag: int
    expires_at: datetime
    created_by: str

    manifest_sha256: str
    part_bytes: int
    files: list[IngestFileView]
