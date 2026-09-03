"""Consumer-owned protocols; implementing packages conform structurally.

Every capability the catalog needs from outside - a clock, the raw store,
the metastore, the search projection, credential vending, job dispatch,
principal resolution - is declared here as a :class:`typing.Protocol`, in
terms of what the catalog needs and nothing more. The packages that provide
these capabilities never import this module: they satisfy a protocol by
shape, and a service composes the two. That is what keeps ``pkg/catalog``
free of every sibling package and lets a test substitute any port with a
few lines of fake.

The methods here have no bodies. Each docstring is the contract: what an
implementation must guarantee to callers that see only this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import PurePosixPath
    from uuid import UUID

    from .ingest import IngestLease
    from .models import OutboxEvent, RevisionRecord, RevisionRef


class Clock(Protocol):
    """The source of the current time, injected so lease arithmetic is testable."""

    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            A timezone-aware UTC datetime, comparable with every
            ``expires_at`` the catalog stores.
        """
        ...


class RawStore(Protocol):
    """The raw evidence tier: staging, hard-linking, atomic commit, sealing, write-once tags.

    An implementation owns one data root laid out by
    :mod:`huron.pkg.catalog.paths`; the catalog hands it paths from that
    module and never composes its own.
    """

    def create_staging(self, ingest_id: UUID) -> PurePosixPath:
        """Create the private staging envelope for one ingest session.

        The envelope must be on the same filesystem as the final revision
        directories, because :meth:`commit_envelope` publishes it with a
        rename and :meth:`hardlink_from_parent` links into it. It must be
        fresh: a second call for the same session must fail rather than
        hand back a directory another driver may be writing.

        Args:
            ingest_id: The session the envelope belongs to.

        Returns:
            The envelope's directory, holding an empty ``payload/`` child
            ready for uploads and links.
        """
        ...

    def hardlink_from_parent(
        self, parent_payload: PurePosixPath, staging_payload: PurePosixPath, rel_path: str
    ) -> None:
        """Reuse one unchanged file from the parent revision without copying its bytes.

        The file at ``rel_path`` under ``parent_payload`` must appear at the
        same relative path under ``staging_payload``, creating intermediate
        directories as needed. A hard link is the intent; an implementation
        that cannot link may copy, but the result must be byte-identical
        and must not disturb the parent.

        Args:
            parent_payload: The committed parent revision's ``payload``
                directory.
            staging_payload: The staging envelope's ``payload`` directory.
            rel_path: The file's path relative to both payload directories.
        """
        ...

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        """Publish a complete staging envelope at its final path, all or nothing.

        After this returns, ``final`` holds everything ``staging`` held and
        is durable; if it raises, ``final`` does not exist and ``staging``
        is untouched. A reader can never observe a half-published revision.
        Committing an envelope that is already published at ``final``, with
        no staging directory left, must succeed silently so a crashed
        driver can retry; any other pre-existing ``final`` must be refused.

        Args:
            staging: The envelope to publish, complete and marked committed.
            final: The revision directory to publish it as.
        """
        ...

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Make a published revision read-only, recursively.

        Every file and directory under ``revision_dir`` loses write
        permission, so nothing short of an administrator undoing the seal
        can alter committed evidence.

        Args:
            revision_dir: The published revision directory.
        """
        ...

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None:
        """Write a release tag file that must not already exist.

        Creation is exclusive: if ``tag_file`` exists the call must fail
        without touching it, which is what makes a release tag resolve to
        one revision forever even under concurrent tagging. The payload
        must be durable when the call returns.

        Args:
            tag_file: The tag's path, from
                :func:`huron.pkg.catalog.paths.release_tag_file`.
            payload: The tag document's canonical bytes.
        """
        ...


class Metastore(Protocol):
    """The transactional record of ingests, revisions and release tags.

    The metastore is the source of truth for what has been committed; the
    raw store holds the bytes, the metastore says which of them are a
    revision.
    """

    async def begin_ingest(self, dataset_id: UUID, manifest_sha256: str) -> IngestLease:
        """Open an ingest session and reserve the revision it will commit as.

        The revision id and number are allocated here, before any byte is
        uploaded, so the number is unique within the dataset for the life
        of the session even if the session is later aborted; numbers are
        not reused. The manifest identity is recorded with the session so
        the commit can be checked against what was declared.

        Args:
            dataset_id: The dataset the revision is being added to.
            manifest_sha256: The content identity of the declared manifest.

        Returns:
            The lease: the session id, the reserved revision id and number,
            and when the lease lapses unless renewed.
        """
        ...

    async def record_revision(self, revision: RevisionRecord, outbox: list[OutboxEvent]) -> None:
        """Record a published revision and its outbox events in one transaction.

        Either the revision row and every event are durable together, or
        none of them is: a consumer of the outbox can never see an event
        for a revision the metastore does not know, and a recorded revision
        can never go unannounced.

        Args:
            revision: The committed revision as the raw store published it.
            outbox: The events announcing it, delivered after the commit.
        """
        ...

    async def resolve_tag(self, dataset_id: UUID, tag: str) -> RevisionRef:
        """Look up the revision a release tag names.

        A tag resolves to the same revision for as long as it exists; the
        manifest identity travels with the answer so a caller can verify
        the revision it then reads.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag.

        Returns:
            The revision's id, dataset, number and manifest identity.
        """
        ...


class SearchProjection(Protocol):
    """The read-optimized search index, fed from the catalog and never authoritative.

    The projection can lag or be down; the catalog treats it as derived
    data that is rebuilt from the metastore, never as a fallback source of
    truth.
    """

    async def upsert(self, table: str, rows: list[dict[str, object]]) -> None:
        """Insert or replace rows in one projection table.

        Applying the same rows twice must leave the table as applying them
        once would, so a replayed outbox event is harmless.

        Args:
            table: The projection table the rows belong to.
            rows: The rows, each carrying its own key.
        """
        ...

    async def query(self, query: str, visible_project_ids: list[UUID]) -> list[dict[str, object]]:
        """Search the projection, confined to the projects the caller may see.

        Visibility is decided by the caller from its bindings and passed
        in; the projection must return nothing from a project outside
        ``visible_project_ids``, whatever the query says.

        Args:
            query: The caller's search text.
            visible_project_ids: The projects whose entries may appear.

        Returns:
            The matching rows, best match first.
        """
        ...


class ScopedCredentials(Protocol):
    """Short-lived credentials for one storage prefix, with the instant they stop working."""

    expires_at: datetime


class CredentialVendor(Protocol):
    """The issuer of short-lived, prefix-scoped storage credentials."""

    async def vend_read_only(self, repo_prefix: str, ttl_seconds: int) -> ScopedCredentials:
        """Issue credentials that can read one repository prefix and nothing else.

        The credentials must be unable to write anywhere or read outside
        ``repo_prefix``, and must stop working no later than
        ``ttl_seconds`` after issue; the returned ``expires_at`` says when.

        Args:
            repo_prefix: The storage prefix the credentials may read.
            ttl_seconds: How long, at most, the credentials stay valid.

        Returns:
            The credentials and their expiry.
        """
        ...


class JobDispatcher(Protocol):
    """The launcher for pipeline jobs, addressed by the entity they act on."""

    async def submit(
        self, kind: str, subject_id: UUID, image_digest: str, env: dict[str, str]
    ) -> UUID:
        """Queue one job and return its identifier.

        The image is named by digest, not tag, so what ran is recorded
        exactly and a job can be reproduced later.

        Args:
            kind: The job type the runtime dispatches on.
            subject_id: The entity the job acts on.
            image_digest: The digest of the container image to run.
            env: Environment variables the job starts with.

        Returns:
            The job's identifier, for tracking its outcome.
        """
        ...


class Principal(Protocol):
    """Whoever a credential resolved to, reduced to the subject string bindings name."""

    subject: str


class PrincipalResolver(Protocol):
    """The authenticator: turns a presented credential into a principal, or refuses."""

    async def resolve(self, credential: str) -> Principal:
        """Identify the principal a credential belongs to.

        A credential that is unknown, expired or revoked must be refused
        with an error, never resolved to a guest; the catalog has no notion
        of an anonymous principal.

        Args:
            credential: The bearer credential as presented.

        Returns:
            The principal, carrying at least the subject bindings refer to.
        """
        ...
