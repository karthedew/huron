"""Small immutable values shared by the framework-free catalog modules.

These are the record shapes the catalog's ports exchange with the services
that implement them: enough identity to build a storage path, enough about
a committed revision to record it, and the event that announces it. They
carry no behaviour and no framework import, so both sides of a port can use
them without either importing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class EntityRef:
    """The identity of an organization, project or dataset as a storage path needs it.

    An id plus a slug is exactly what the path constructors in
    :mod:`huron.pkg.catalog.paths` take (they spell ``{slug}--{id}``), so
    this frozen value satisfies their ``Slugged`` protocol - whose ``id``
    and ``slug`` are read-only properties, not settable attributes -
    without the full record.

    Attributes:
        id: The entity's identifier.
        slug: The entity's URL- and path-safe name.
    """

    id: UUID
    slug: str


@dataclass(frozen=True, slots=True)
class RevisionRef:
    """What a release tag resolves to: one revision, named by id and number.

    Attributes:
        id: The revision's identifier.
        dataset_id: The dataset the revision belongs to.
        number: The revision's 1-based position within its dataset.
        manifest_sha256: The content identity of the revision's manifest,
            so a resolver can prove it got the revision it asked for.
    """

    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """A committed raw revision as the catalog records it.

    Built once the envelope is published and never updated: a revision is
    immutable, so its record is too.

    Attributes:
        id: The revision's identifier.
        dataset_id: The dataset the revision belongs to.
        number: The revision's 1-based position within its dataset.
        manifest_sha256: The content identity of the committed manifest.
        metadata_sha256: The content identity of the committed
            ``metadata.json`` document.
        revision_path: The revision directory in the raw store, as
            :func:`huron.pkg.catalog.paths.revision_dir` builds it.
        committed_by: The principal whose ingest session committed it.
        committed_at: When the commit became durable.
        file_count: How many files the manifest lists.
        total_bytes: The sum of the manifest's file sizes.
    """

    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str
    metadata_sha256: str
    revision_path: str
    committed_by: str
    committed_at: datetime
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """An event stored in the same transaction as the change it announces.

    Writing the event through a transactional outbox, rather than publishing
    it directly, means a consumer can never learn of a revision that was
    not durably recorded, and a recorded revision can never go unannounced.

    Attributes:
        id: The event's identifier, minted at the raise site.
        kind: The event type a consumer dispatches on.
        subject_id: The id of the entity the event is about.
        payload: The event body, as JSON-compatible values.
        created_at: When the event was recorded, alongside the change it
            announces.
    """

    id: UUID
    kind: str
    subject_id: UUID
    payload: dict[str, object]
    created_at: datetime
