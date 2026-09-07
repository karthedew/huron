"""Request and response bodies owned by ``endpoints/ingest_sessions.py``'s commit route.

``MetadataSubmission`` is the client's half of a revision's ``metadata.json``
document; the server-sourced half (identity, provenance, the instant) is
composed onto it by :mod:`huron.pkg.catalog.documents`, never accepted from
the wire. ``RevisionView`` is what a committed revision publishes over HTTP.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MetadataSubmission(BaseModel):
    """The committer's half of ``metadata.json``: description, never identity or provenance.

    Extra fields are refused rather than silently dropped, so a client
    that mistypes a member name or tries to set a server-sourced one
    (``committed_by``, ``committed_at``) is told at the schema boundary
    instead of having the value vanish. Content rules beyond shape -
    non-empty titles, unique tags and the rest - belong to the registered
    metadata schema, not to this model, so there is exactly one authority
    for them.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    creators: list[str]
    description: str | None = None
    tags: list[str] | None = None
    source: dict[str, object] | None = None
    coverage: dict[str, object] | None = None
    extensions: dict[str, object] | None = None


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
