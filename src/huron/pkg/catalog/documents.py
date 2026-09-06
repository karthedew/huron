"""The four documents a committed revision leaves on disk, as validating value objects.

Every document here is written and read as canonical bytes (RFC 8785): a
value object's only constructors are classmethods that validate against its
packaged schema, so an instance in memory always conforms and its canonical
bytes and content identity are properties of it, never recomputed by a
caller. ``metadata.json`` and the ``COMMITTED`` marker compose the server's
own provenance and identity members around whatever the client submitted;
``INDEX.json`` is a derived navigation aid whose canonical bytes depend only
on the set of revisions it lists, never on when it was written. Decoding any
of the three refuses bytes that are not their own canonical form, so a
hand-edited or pretty-printed file is caught at first read rather than
silently re-identified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast
from uuid import UUID

from jsonschema import ValidationError

from huron.schema import validate

from .errors import ContractMismatch
from .manifest import (
    JsonValue,
    Manifest,
    ManifestEntry,
    canonical_bytes,
    content_identity,
    validate_manifest,
)
from .models import RevisionRecord

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .ingest import IngestSession
    from .paths import Slugged

METADATA_SCHEMA = "urn:huron:metadata:1"
COMMITTED_SCHEMA = "urn:huron:committed:1"
INDEX_SCHEMA = "urn:huron:revision-index:1"

#: The metadata-v1 members the server sources; a submission naming any of
#: these is a caller bug, refused before schema validation runs.
SERVER_METADATA_MEMBERS: frozenset[str] = frozenset(
    {
        "schema",
        "organization",
        "project",
        "dataset",
        "revision_number",
        "committed_by",
        "committed_at",
        "manifest_sha256",
        "data_classification",
    }
)


def _decode_canonical(payload: bytes) -> dict[str, JsonValue]:
    """Parse a stored document and refuse bytes that are not its own canonical form.

    Args:
        payload: The document's bytes exactly as stored.

    Returns:
        The parsed JSON object.

    Raises:
        ValueError: If ``payload`` is not valid JSON, its top level is not
            an object, or re-serializing it does not reproduce ``payload``
            byte for byte.
    """
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("stored document is not a JSON object")
    if canonical_bytes(cast("Mapping[str, object]", parsed)) != payload:
        raise ValueError("stored document is not its own canonical form")
    return cast("dict[str, JsonValue]", parsed)


def _render_instant(instant: datetime) -> str:
    """Render a timezone-aware instant as RFC 3339 with a ``Z`` suffix.

    Args:
        instant: The instant to render; converted to UTC first so the
            result always ends in ``Z`` rather than ``+00:00``.

    Returns:
        The instant as ``YYYY-MM-DDTHH:MM:SS(.ffffff)Z``.
    """
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_instant(value: str) -> datetime:
    """Parse an RFC 3339 instant rendered by :func:`_render_instant`.

    Args:
        value: The stored instant, ending in ``Z``.

    Returns:
        The instant, timezone-aware in UTC.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ref(entity: Slugged) -> dict[str, JsonValue]:
    """Render an organization, project or dataset as metadata's identity block.

    Args:
        entity: The entity to render.

    Returns:
        Its id and slug, as metadata-v1's reference shape requires.
    """
    return {"id": str(entity.id), "slug": entity.slug}


def manifest_bytes(manifest: Manifest) -> bytes:
    """Render the ``manifest.json`` document for a validated manifest.

    Args:
        manifest: The manifest to render.

    Returns:
        The manifest's RFC 8785 canonical bytes; their SHA-256 is
        ``manifest.sha256``.
    """
    return canonical_bytes(manifest.as_dict())


def decode_manifest(payload: bytes) -> Manifest:
    """Rebuild a manifest from stored ``manifest.json`` bytes.

    The entries are handed to :func:`validate_manifest`, so every layout
    and size rule it enforces applies again here and its refusals
    (``PathRuleViolation``, ``EmptyRevision``, ``FileTooLarge`` and the
    rest) propagate unchanged.

    Args:
        payload: The document's bytes exactly as stored.

    Returns:
        The manifest, revalidated against every layout and size rule.

    Raises:
        ValueError: If the bytes are not their own canonical form, are not
            valid JSON, or fail manifest-v1.
    """
    document = _decode_canonical(payload)
    try:
        validate("manifest-v1.json", document)
    except ValidationError as err:
        raise ValueError(str(err)) from err
    files = cast("list[dict[str, JsonValue]]", document["files"])
    entries = [
        ManifestEntry(
            path=cast("str", file["path"]),
            size=cast("int", file["size"]),
            sha256=cast("str", file["sha256"]),
            media_type=cast("str", file["media_type"]),
        )
        for file in files
    ]
    return validate_manifest(entries)


@dataclass(frozen=True, slots=True)
class MetadataDocument:
    """One revision's descriptive snapshot, exactly as ``metadata.json`` holds it.

    Always conforms to metadata-v1: the only constructors are
    :meth:`compose`, which assembles and validates a new document, and
    :meth:`decode`, which rebuilds one already proven to conform.
    """

    _document: Mapping[str, JsonValue]

    @classmethod
    def compose(
        cls,
        submission: Mapping[str, JsonValue],
        *,
        manifest: Manifest,
        organization: Slugged,
        project: Slugged,
        dataset: Slugged,
        revision_number: int,
        committed_by: str,
        committed_at: datetime,
        data_classification: str,
    ) -> MetadataDocument:
        """Assemble the client's descriptive members under the server's own.

        Args:
            submission: The committer's descriptive members; must not name
                any member the server owns.
            manifest: The manifest being committed, supplying its content
                identity.
            organization: The dataset's owning organization.
            project: The dataset's owning project.
            dataset: The dataset the revision belongs to.
            revision_number: The revision's 1-based position in the
                dataset.
            committed_by: The principal driving the commit.
            committed_at: The instant the commit became durable; must be
                timezone-aware.
            data_classification: The classification governing who may
                read the revision.

        Returns:
            The composed, schema-conformant document.

        Raises:
            ValueError: If ``submission`` names a server-owned member, or
                ``committed_at`` is not timezone-aware.
            ContractMismatch: If the assembled document violates
                metadata-v1; ``context`` carries the schema, the violating
                path and the message.
        """
        reserved = set(submission) & SERVER_METADATA_MEMBERS
        if reserved:
            raise ValueError(f"submission may not set server-owned members: {sorted(reserved)}")
        if committed_at.tzinfo is None:
            raise ValueError("committed_at must be timezone-aware")
        document: dict[str, JsonValue] = {
            "schema": METADATA_SCHEMA,
            "organization": _ref(organization),
            "project": _ref(project),
            "dataset": _ref(dataset),
            "revision_number": revision_number,
            "committed_by": committed_by,
            "committed_at": _render_instant(committed_at),
            "data_classification": data_classification,
            "manifest_sha256": manifest.sha256,
            **submission,
        }
        try:
            validate("metadata-v1.json", document)
        except ValidationError as err:
            raise ContractMismatch(
                context={"schema": METADATA_SCHEMA, "path": err.json_path, "message": err.message}
            ) from err
        return cls(document)

    @classmethod
    def decode(cls, payload: bytes) -> MetadataDocument:
        """Rebuild a metadata document from stored bytes.

        Args:
            payload: The document's bytes exactly as stored.

        Returns:
            The decoded document.

        Raises:
            ValueError: If the bytes are not their own canonical form, are
                not valid JSON, or fail metadata-v1.
        """
        document = _decode_canonical(payload)
        try:
            validate("metadata-v1.json", document)
        except ValidationError as err:
            raise ValueError(str(err)) from err
        return cls(document)

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the document as a fresh, independently mutable copy.

        Returns:
            A shallow copy of the document's members.
        """
        return dict(self._document)

    @property
    def canonical(self) -> bytes:
        """Return the document's RFC 8785 canonical bytes, as written to storage.

        Returns:
            The canonical serialization of the document.
        """
        return canonical_bytes(self._document)

    @property
    def sha256(self) -> str:
        """Return the document's content identity.

        Returns:
            The SHA-256 of the document's canonical bytes; this is the
            ``metadata_sha256`` a revision record carries.
        """
        return content_identity(self._document)

    @property
    def manifest_sha256(self) -> str:
        """Return the manifest content identity the document was composed against.

        Returns:
            The ``manifest_sha256`` member, unchanged from what
            :meth:`compose` or :meth:`decode` established.
        """
        return cast("str", self._document["manifest_sha256"])

    @property
    def committed_by(self) -> str:
        """Return the principal who drove the commit.

        Returns:
            The ``committed_by`` member.
        """
        return cast("str", self._document["committed_by"])

    @property
    def committed_at(self) -> datetime:
        """Return the instant the commit became durable.

        Returns:
            The ``committed_at`` member, parsed as a timezone-aware UTC
            instant.
        """
        return _parse_instant(cast("str", self._document["committed_at"]))


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """The ``COMMITTED`` marker: a revision record without its storage location.

    A document must not name its own location, so every field of
    :class:`~huron.pkg.catalog.models.RevisionRecord` travels here except
    ``revision_path``; :meth:`revision_record` restores it from wherever the
    marker was actually read.
    """

    revision_id: UUID
    dataset_id: UUID
    revision_number: int
    manifest_sha256: str
    metadata_sha256: str
    file_count: int
    total_bytes: int
    committed_by: str
    committed_at: datetime

    @classmethod
    def of(cls, record: RevisionRecord) -> CommitRecord:
        """Take every field of a revision record but its storage location.

        Args:
            record: The revision record to render as a marker.

        Returns:
            The marker for ``record``.
        """
        return cls(
            revision_id=record.id,
            dataset_id=record.dataset_id,
            revision_number=record.number,
            manifest_sha256=record.manifest_sha256,
            metadata_sha256=record.metadata_sha256,
            file_count=record.file_count,
            total_bytes=record.total_bytes,
            committed_by=record.committed_by,
            committed_at=record.committed_at,
        )

    @classmethod
    def decode(cls, payload: bytes) -> CommitRecord:
        """Rebuild a marker from stored ``COMMITTED`` bytes.

        Args:
            payload: The document's bytes exactly as stored.

        Returns:
            The decoded marker.

        Raises:
            ValueError: If the bytes are not their own canonical form, are
                not valid JSON, or fail committed-v1.
        """
        document = _decode_canonical(payload)
        try:
            validate("committed-v1.json", document)
        except ValidationError as err:
            raise ValueError(str(err)) from err
        return cls(
            revision_id=UUID(cast("str", document["revision_id"])),
            dataset_id=UUID(cast("str", document["dataset_id"])),
            revision_number=cast("int", document["revision_number"]),
            manifest_sha256=cast("str", document["manifest_sha256"]),
            metadata_sha256=cast("str", document["metadata_sha256"]),
            file_count=cast("int", document["file_count"]),
            total_bytes=cast("int", document["total_bytes"]),
            committed_by=cast("str", document["committed_by"]),
            committed_at=_parse_instant(cast("str", document["committed_at"])),
        )

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the marker as the ``COMMITTED`` JSON document.

        Returns:
            The document with every committed-v1 required member.
        """
        return {
            "schema": COMMITTED_SCHEMA,
            "revision_id": str(self.revision_id),
            "dataset_id": str(self.dataset_id),
            "revision_number": self.revision_number,
            "manifest_sha256": self.manifest_sha256,
            "metadata_sha256": self.metadata_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "committed_by": self.committed_by,
            "committed_at": _render_instant(self.committed_at),
        }

    @property
    def canonical(self) -> bytes:
        """Return the marker's RFC 8785 canonical bytes, as written to storage.

        Returns:
            The canonical serialization of :meth:`as_dict`.
        """
        return canonical_bytes(self.as_dict())

    def revision_record(self, *, revision_path: str) -> RevisionRecord:
        """Rebuild the revision record this marker describes.

        Args:
            revision_path: The revision's directory, as read from storage.

        Returns:
            The record :meth:`of` was built from, at ``revision_path``.
        """
        return RevisionRecord(
            id=self.revision_id,
            dataset_id=self.dataset_id,
            number=self.revision_number,
            manifest_sha256=self.manifest_sha256,
            metadata_sha256=self.metadata_sha256,
            revision_path=revision_path,
            committed_by=self.committed_by,
            committed_at=self.committed_at,
            file_count=self.file_count,
            total_bytes=self.total_bytes,
        )


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One committed revision as ``INDEX.json`` lists it.

    Attributes:
        number: The revision's 1-based position within its dataset.
        revision_id: The revision's identifier.
        directory: The revision directory's basename.
        manifest_sha256: The content identity of the committed manifest.
        metadata_sha256: The content identity of the committed metadata
            document.
        file_count: How many files the manifest lists.
        total_bytes: The sum of the manifest's file sizes.
        committed_at: When the commit became durable.
    """

    number: int
    revision_id: UUID
    directory: str
    manifest_sha256: str
    metadata_sha256: str
    file_count: int
    total_bytes: int
    committed_at: datetime


def _entry_as_dict(entry: IndexEntry) -> dict[str, JsonValue]:
    """Render one index entry as ``INDEX.json``'s ``revisions`` member holds it.

    Args:
        entry: The entry to render.

    Returns:
        The entry as a JSON object.
    """
    return {
        "number": entry.number,
        "revision_id": str(entry.revision_id),
        "directory": entry.directory,
        "manifest_sha256": entry.manifest_sha256,
        "metadata_sha256": entry.metadata_sha256,
        "file_count": entry.file_count,
        "total_bytes": entry.total_bytes,
        "committed_at": _render_instant(entry.committed_at),
    }


def _entry_from_dict(entry: Mapping[str, JsonValue]) -> IndexEntry:
    """Rebuild one index entry from its ``INDEX.json`` representation.

    Args:
        entry: The entry's JSON object, already schema-validated.

    Returns:
        The decoded entry.
    """
    return IndexEntry(
        number=cast("int", entry["number"]),
        revision_id=UUID(cast("str", entry["revision_id"])),
        directory=cast("str", entry["directory"]),
        manifest_sha256=cast("str", entry["manifest_sha256"]),
        metadata_sha256=cast("str", entry["metadata_sha256"]),
        file_count=cast("int", entry["file_count"]),
        total_bytes=cast("int", entry["total_bytes"]),
        committed_at=_parse_instant(cast("str", entry["committed_at"])),
    )


@dataclass(frozen=True, slots=True)
class RevisionIndex:
    """The navigation aid beside a dataset's revision directories.

    One entry per committed revision, ascending and unique by number; the
    same set of revisions always renders the same canonical bytes, so
    staleness can be detected by comparing digests rather than a clock.

    Attributes:
        dataset_id: The dataset the index belongs to.
        entries: The dataset's committed revisions, ascending by number.
    """

    dataset_id: UUID
    entries: tuple[IndexEntry, ...]

    @classmethod
    def empty(cls, dataset_id: UUID) -> RevisionIndex:
        """Build the index for a dataset with no committed revisions yet.

        Args:
            dataset_id: The dataset the index belongs to.

        Returns:
            An index with no entries.
        """
        return cls(dataset_id=dataset_id, entries=())

    @classmethod
    def decode(cls, payload: bytes) -> RevisionIndex:
        """Rebuild an index from stored ``INDEX.json`` bytes.

        Args:
            payload: The document's bytes exactly as stored.

        Returns:
            The decoded index.

        Raises:
            ValueError: If the bytes are not their own canonical form, are
                not valid JSON, fail revision-index-v1, or the entries are
                not strictly ascending and unique by number.
        """
        document = _decode_canonical(payload)
        try:
            validate("revision-index-v1.json", document)
        except ValidationError as err:
            raise ValueError(str(err)) from err
        entries = tuple(
            _entry_from_dict(entry)
            for entry in cast("list[Mapping[str, JsonValue]]", document["revisions"])
        )
        numbers = [entry.number for entry in entries]
        if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
            raise ValueError("revision index entries must be strictly ascending by number")
        return cls(dataset_id=UUID(cast("str", document["dataset_id"])), entries=entries)

    def including(self, record: RevisionRecord) -> RevisionIndex:
        """Return the index with one revision's entry added or replaced.

        Args:
            record: The revision to include, at its own number.

        Returns:
            A new index with ``record``'s entry present at its number and
            every other entry unchanged, sorted ascending by number.

        Raises:
            ValueError: If ``record`` belongs to a different dataset.
        """
        if record.dataset_id != self.dataset_id:
            raise ValueError("record belongs to a different dataset")
        entry = IndexEntry(
            number=record.number,
            revision_id=record.id,
            directory=PurePosixPath(record.revision_path).name,
            manifest_sha256=record.manifest_sha256,
            metadata_sha256=record.metadata_sha256,
            file_count=record.file_count,
            total_bytes=record.total_bytes,
            committed_at=record.committed_at,
        )
        remaining = (existing for existing in self.entries if existing.number != record.number)
        merged = tuple(sorted((*remaining, entry), key=lambda item: item.number))
        return RevisionIndex(dataset_id=self.dataset_id, entries=merged)

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the index as the ``INDEX.json`` document.

        Returns:
            The document with every revision-index-v1 required member.
        """
        return {
            "schema": INDEX_SCHEMA,
            "dataset_id": str(self.dataset_id),
            "revisions": [_entry_as_dict(entry) for entry in self.entries],
        }

    @property
    def canonical(self) -> bytes:
        """Return the index's RFC 8785 canonical bytes, as written to storage.

        Returns:
            The canonical serialization of :meth:`as_dict`.
        """
        return canonical_bytes(self.as_dict())


def revision_from_storage(
    committed: bytes, metadata: bytes, *, session: IngestSession, revision_path: str
) -> RevisionRecord:
    """Rebuild the row a published envelope describes.

    Used by a commit retry that lands after the envelope's rename: the
    marker and the metadata document are proof enough that the revision
    was published, as long as they agree with each other and with the
    session that wrote them.

    Args:
        committed: The ``COMMITTED`` marker's bytes, exactly as stored.
        metadata: The ``metadata.json`` document's bytes, exactly as
            stored.
        session: The session driving the retried commit.
        revision_path: The revision's directory in the raw store.

    Returns:
        The revision record the envelope describes.

    Raises:
        ValueError: If the marker or the metadata document is malformed,
            or they disagree with each other or with the session on
            identity, digests, committer or instant.
    """
    record = CommitRecord.decode(committed)
    doc = MetadataDocument.decode(metadata)
    lease = session.lease
    observed = (
        doc.sha256,
        record.manifest_sha256,
        doc.manifest_sha256,
        record.revision_id,
        record.dataset_id,
        record.revision_number,
        record.committed_by,
        record.committed_at,
    )
    expected = (
        record.metadata_sha256,
        session.manifest_sha256,
        session.manifest_sha256,
        lease.revision_id,
        lease.dataset_id,
        lease.revision_number,
        doc.committed_by,
        doc.committed_at,
    )
    if observed != expected:
        raise ValueError("the committed marker and metadata document disagree with the session")
    return record.revision_record(revision_path=revision_path)
