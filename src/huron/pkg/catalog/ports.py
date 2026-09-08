"""Consumer-owned protocols; implementing packages conform structurally.

Every capability the catalog needs from outside - a clock, the raw store,
the search projection, credential vending, job dispatch, principal
resolution - is declared here as a :class:`typing.Protocol`, in
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
    import os
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime
    from pathlib import Path, PurePosixPath
    from uuid import UUID


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
    """Everything the service asks of the raw filesystem.

    One root, private envelopes, durable parts and links, documents,
    publication by rename, sealing and write-once tags. An implementation
    owns one data root laid out by :mod:`huron.pkg.catalog.paths`; the
    catalog hands it paths from that module and never composes its own.
    """

    @property
    def root(self) -> Path:
        """Return the data root every other path is derived from.

        Returns:
            The directory ``.staging/`` and ``organization/`` sit under as
            direct children; nothing links or renames a path across
            different roots.
        """
        ...

    def initialize(self) -> None:
        """Create the store's directory skeleton and prove it can commit.

        Creates ``.staging`` and ``organization`` if they are missing; the
        call is idempotent, and both directories must end up on one
        filesystem, because :meth:`commit_envelope` publishes an envelope
        with a rename between them. A cross-device layout is refused as a
        ``CrossDeviceCommitError``.
        """
        ...

    def create_staging(self, staging: PurePosixPath) -> None:
        """Claim a fresh, private envelope for one ingest session.

        The envelope and its ``payload`` child are created at mode
        ``0o700``, visible to nobody but the store's own process until the
        envelope is published. A ``staging`` whose parent is not
        ``root/.staging`` is refused as a ``ValueError``; a name already
        claimed fails as a ``FileExistsError`` rather than handing back a
        directory another driver may be writing.

        Args:
            staging: The envelope's path, from
                :func:`huron.pkg.catalog.paths.staging_dir`.
        """
        ...

    def write_part(
        self,
        staging_payload: PurePosixPath,
        rel_path: str,
        chunks: Iterable[bytes],
        *,
        offset: int,
        length: int,
    ) -> str:
        """Stream one range of a payload file into place, hashing as it goes.

        Exactly ``length`` bytes are pulled from ``chunks``, in order, and
        written to ``[offset, offset + length)`` of the file at
        ``rel_path``; nothing outside that range is touched, so parts of
        one file may arrive in any order and a resend overwrites only its
        own bytes. An unsafe ``rel_path`` is refused as a ``ValueError``
        before anything opens; a stream that ends short or runs long is
        refused as a ``PartLengthMismatchError`` before any success is
        reported. The file and every directory from its parent up to
        ``staging_payload`` must be durable before the digest is returned.

        Args:
            staging_payload: The envelope's ``payload`` directory.
            rel_path: The file's path relative to ``staging_payload``.
            chunks: The range's bytes, consumed once, in order.
            offset: The first byte position the range writes to.
            length: The exact number of bytes the range must contain.

        Returns:
            The hex SHA-256 of the bytes written.
        """
        ...

    def finish_file(
        self,
        staging: PurePosixPath,
        file_id: str,
        rel_path: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> tuple[int, str]:
        """Install independently copied, verified bytes without replacing a winner.

        Args:
            staging: Existing session root; never recreated.
            file_id: Upload input name.
            rel_path: Manifest payload path.
            expected_size: Declared byte count.
            expected_sha256: Declared digest.

        Returns:
            Actual observation; mismatch installs nothing and removes only its candidate.
        """
        ...

    def verify_envelope(
        self,
        envelope: PurePosixPath,
        files: Sequence[tuple[str, int, str]],
        documents: Mapping[str, bytes],
    ) -> None:
        """Check exact inventory, independent sealed inodes and frozen evidence.

        Args:
            envelope: Existing staged or final envelope.
            files: Manifest paths, sizes and digests.
            documents: Frozen control document bytes.
        """
        ...

    def discard_file(self, staging_payload: PurePosixPath, rel_path: str) -> None:
        """Remove a payload file the ledger no longer vouches for.

        A missing file is success.

        Args:
            staging_payload: The envelope's ``payload`` directory.
            rel_path: The file's path relative to ``staging_payload``.
        """
        ...

    def read_document(self, path: PurePosixPath) -> bytes:
        """Return a stored document's bytes exactly as written.

        A path storage does not hold is refused as a ``FileNotFoundError``.

        Args:
            path: The document's path.

        Returns:
            The document's content.
        """
        ...

    def stat_document(self, path: PurePosixPath) -> os.stat_result:
        """Inspect a stored file without reading its contents.

        Args:
            path: The stored file's location.

        Returns:
            Its current filesystem metadata.
        """
        ...

    def write_document(self, staging: PurePosixPath, name: str, payload: bytes) -> None:
        """Durably place a control document at the envelope root.

        ``name`` must be a single path component and none of the reserved
        names, refused otherwise as a ``ValueError``; the file is written
        read-only, and a second call with the same name replaces its bytes
        wholesale, never leaving a mix of an earlier attempt's content and
        the new one.

        Args:
            staging: The envelope's root directory.
            name: The document's file name.
            payload: The document's complete content.
        """
        ...

    def atomic_replace(self, path: PurePosixPath, payload: bytes) -> None:
        """Replace a file's content in one step, durable when this returns.

        A reader sees the old bytes or the new, never a mix; for pointers
        and other derived aids that move rather than write once.

        Args:
            path: The file to replace; created if it does not exist yet.
            payload: The complete new content.
        """
        ...

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Make everything below a directory read-only, the directory itself untouched.

        Every file below ``revision_dir`` becomes ``0o444`` and every
        directory below it ``0o555``; ``revision_dir`` itself is left alone
        so it can still be renamed by whatever publishes it next.
        Idempotent. A ``revision_dir`` that is not a directory is refused
        as a ``FileNotFoundError``.

        Args:
            revision_dir: The directory whose contents are sealed.
        """
        ...

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        """Publish a complete staging envelope at its final path, all or nothing.

        The envelope is fsynced, revealed by one rename, and then ``final``
        itself is sealed; the rename is the only step that changes what is
        visible at ``final``, so a reader can never observe a half-
        published revision. After this returns, ``final`` holds everything
        ``staging`` held and ``staging`` is gone; if it raises, ``final``
        does not exist and ``staging`` is untouched. Committing an envelope
        that is already published at ``final``, with no staging directory
        left, succeeds silently so a crashed driver can retry; any other
        pre-existing ``final`` is refused as a ``FileExistsError``, a
        ``staging`` that is not a directory as a ``FileNotFoundError``, one
        without a ``COMMITTED`` marker as a ``ValueError``, and a
        cross-device pair as a ``CrossDeviceCommitError``.

        Args:
            staging: The envelope to publish, complete and marked committed.
            final: The revision directory to publish it as.
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

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Record one generation of an entity document and point ``CURRENT.json`` at it.

        A ``generation`` outside ``1..999_999`` is refused as a
        ``ValueError``.

        Args:
            entity_dir: The organization, project or dataset directory.
            generation: The document's generation number, ``1`` to
                ``999_999``.
            payload: The canonical bytes of the document.

        Returns:
            The path of the generation file that was written.
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
