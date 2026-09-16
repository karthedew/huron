"""Request and response bodies owned by ``endpoints/ingest_sessions.py``'s commit route.

``MetadataSubmission`` is the client's half of a revision's ``metadata.json``
document; the server-sourced half (identity, provenance, the instant) is
composed onto it by :mod:`huron.core.raw.documents`, never accepted from
the wire. ``RevisionView`` is what a committed revision publishes over HTTP.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from huron.core.raw.metadata import MetadataSubmission

__all__ = ["MetadataSubmission", "RevisionView"]


class RevisionView(BaseModel):
    """A committed revision as the catalog records it; the storage location is not wire contract."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str
    metadata_sha256: str
    file_count: int
    total_bytes: int
    committed_by: str
    committed_at: datetime
