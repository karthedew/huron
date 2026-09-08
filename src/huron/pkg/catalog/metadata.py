"""Caller-supplied revision metadata shared by transports and core workflows."""

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
