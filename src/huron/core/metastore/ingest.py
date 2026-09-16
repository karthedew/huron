"""Ingest-session and per-file ledger mixins for both hierarchy adapters.

``begin_ingest`` and its four companion writes, and the four reads the
expiry sweep and the upload ledger need, are large enough - across two
adapters - that they pulled ``stores/hierarchy.py``'s maintainability rank
down on their own. This module is a size split, not a new port: it holds
mixin bases the transaction writers and the two store classes in
``hierarchy.py`` inherit. The two modules import each other - ``hierarchy``
imports the mixin bases here at runtime, this module imports two of
``hierarchy``'s concrete classes back only for type annotations - so
neither import runs at the other's module-load time and no cycle forms.
The Raw ports are ``HierarchyWriter``/``HierarchyStore`` in ``huron.core.raw.ports``,
and nothing outside ``stores`` imports this module directly - it is
reached, like every other adapter here, only through
``stores/__init__.py``'s public surface.
"""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import chain
from typing import TYPE_CHECKING

import asyncpg

from huron.core.foundation.errors import PreconditionFailed, ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.raw.documents import CommitIntent, CommitRecord
from huron.core.raw.errors import (
    DatasetLocked,
    IngestSessionExpired,
)
from huron.core.raw.ingest import (
    LEASE_TTL,
    TERMINAL_STATES,
    FileState,
    IngestFile,
    IngestLease,
    IngestSession,
    IngestState,
)
from huron.core.raw.types import LedgerEntry

from . import rows

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime
    from uuid import UUID

    from huron.core.foundation.clock import Clock
    from huron.core.raw.types import RevisionRecord

    from .hierarchy import InMemoryHierarchyStore, TransactionBuffer

#: The states ``expire`` and the lapse listing treat as still open.
#: COMMITTING is deliberately excluded from both: once a commit has begun,
#: storage leads and only the driver that started it may finish or fail it
#: - never an expiry sweep or a second allocator. ``renew`` is not gated on
#: this set - a COMMITTING session may still renew, so a ``/commit`` retry
#: that re-enters COMMITTING is never stranded by its own lapsed lease.
_OPEN_INGEST_STATES = frozenset(
    {IngestState.PREPARING, IngestState.UPLOADING, IngestState.VERIFYING}
)

#: Postgres's name for ``ingest_sessions``' per-dataset open-session partial
#: unique index - the allocator's backstop, unreachable under the row lock.
_OPEN_INGEST_SESSION_CONSTRAINT = "one_open_ingest_per_dataset"

#: Every column ``rows.ingest_session`` decodes.
_INGEST_SESSION_COLUMNS = (
    "id, dataset_id, revision_id, revision_number, manifest_sha256, state, etag, expires_at, "
    "created_by"
)

#: Every column ``rows.ingest_file`` decodes.
_INGEST_FILE_COLUMNS = (
    "file_id, path, size, expected_sha256, action, part_count, state, completed_parts"
)

#: The states ``begin_ingest``'s open-session check and the sweep's listing
#: name literally in SQL; kept beside the Python-side ``_OPEN_INGEST_STATES``
#: rather than derived from it, since the two are never bound together.
_TERMINAL_STATE_NAMES = "'COMMITTED', 'ABORTED', 'FAILED'"
_OPEN_STATE_NAMES = "'PREPARING', 'UPLOADING', 'VERIFYING'"


def latest_revision(revisions: Iterable[RevisionRecord], dataset_id: UUID) -> RevisionRecord | None:
    """Return the highest-numbered revision of ``dataset_id`` among ``revisions``, or None.

    Args:
        revisions: The revisions to search, live rows and staged ones alike.
        dataset_id: The dataset whose highest-numbered revision is wanted.

    Returns:
        The matching revision with the greatest ``number``, or None if
        ``revisions`` holds none for ``dataset_id``.
    """
    candidates = [revision for revision in revisions if revision.dataset_id == dataset_id]
    return max(candidates, key=lambda revision: revision.number) if candidates else None


def _find_open_ingest_session(
    sessions: Iterable[IngestSession], dataset_id: UUID
) -> IngestSession | None:
    """Return a non-terminal session of ``dataset_id`` among ``sessions``, or None.

    Args:
        sessions: The sessions to search, live rows and staged ones alike.
        dataset_id: The dataset a new session is being reserved for.

    Returns:
        The matching session, or None if none of ``sessions`` is open for
        ``dataset_id``.
    """
    for session in sessions:
        if session.lease.dataset_id == dataset_id and session.state not in TERMINAL_STATES:
            return session
    return None


def _reserve_ingest_session(
    dataset_id: UUID,
    manifest_sha256: str,
    *,
    created_by: str,
    number: int,
    now: datetime,
) -> IngestSession:
    """Build the session ``begin_ingest`` persists: a fresh lease in PREPARING.

    Shared by both adapters so the reservation's shape - fresh ids, etag 1,
    a lease of exactly ``LEASE_TTL`` - never drifts between them.

    Args:
        dataset_id: The dataset the revision is being added to.
        manifest_sha256: The content identity of the declared manifest.
        created_by: The principal opening the session.
        number: The revision number the allocator computed for this session.
        now: The instant the reservation is made.

    Returns:
        A session in PREPARING, etag 1, leased until ``now + LEASE_TTL``.
    """
    return IngestSession(
        lease=IngestLease(
            ingest_id=uuid7(),
            dataset_id=dataset_id,
            revision_id=uuid7(),
            revision_number=number,
            expires_at=now + LEASE_TTL,
        ),
        state=IngestState.PREPARING,
        manifest_sha256=manifest_sha256,
        created_by=created_by,
    )


def _reserved_file(file: IngestFile) -> IngestFile:
    """Build the ledger row ``begin_ingest`` persists for one planned file.

    A file's ledger always starts PENDING with no parts recorded, whatever
    the caller's ``IngestFile`` carried - the plan's path, size, digest,
    action and part count are what a reservation keeps, not a client's
    premature claim of progress.

    Args:
        file: The plan entry to reserve a ledger row for.

    Returns:
        A copy of ``file`` reset to its just-reserved state.
    """
    return IngestFile(
        file_id=file.file_id,
        path=file.path,
        size=file.size,
        expected_sha256=file.expected_sha256,
        action=file.action,
        part_count=file.part_count,
    )


async def _dataset_row_exists(connection: asyncpg.Connection, dataset_id: UUID) -> bool:
    """Take the row lock that arbitrates concurrent ``begin_ingest`` calls on one dataset.

    Args:
        connection: The connection the enclosing transaction is open on.
        dataset_id: The dataset a new session is being reserved for.

    Returns:
        Whether a dataset has ``dataset_id``, once its row lock is held.
    """
    row = await connection.fetchrow("SELECT id FROM datasets WHERE id = $1 FOR UPDATE", dataset_id)
    return row is not None


async def _pg_open_ingest_session(
    connection: asyncpg.Connection, dataset_id: UUID
) -> asyncpg.Record | None:
    """Return the row of ``dataset_id``'s non-terminal session, once its row lock is held.

    Args:
        connection: The connection the enclosing transaction is open on.
        dataset_id: The dataset a new session is being reserved for.

    Returns:
        The open session's ``id, state, expires_at`` row, or None if it has
        none.
    """
    return await connection.fetchrow(
        f"""
        SELECT id, state, expires_at FROM ingest_sessions
        WHERE dataset_id = $1 AND state NOT IN ({_TERMINAL_STATE_NAMES})
        """,
        dataset_id,
    )


async def _pg_next_revision_number(connection: asyncpg.Connection, dataset_id: UUID) -> int:
    """Return ``max(revision_number) + 1`` over every revision of ``dataset_id``.

    Args:
        connection: The connection the enclosing transaction is open on.
        dataset_id: The dataset to allocate the next number for.

    Returns:
        The next revision number, gap-free across dead sessions because a
        session that never committed left no ``dataset_revisions`` row.
    """
    value = await connection.fetchval(
        "SELECT coalesce(max(revision_number), 0) + 1 FROM dataset_revisions WHERE dataset_id = $1",
        dataset_id,
    )
    return int(value)


class InMemoryIngestWriter:
    """The ingest half of one in-memory transaction's write surface.

    Mixed into ``hierarchy._TransactionWriter``, which supplies ``_store``
    and ``_buffer``; every method here reads and stages exactly as that
    class's other ``insert_*``/``update_*`` methods do.
    """

    _store: InMemoryHierarchyStore
    _buffer: TransactionBuffer

    async def begin_ingest(
        self,
        dataset_id: UUID,
        manifest_sha256: str,
        *,
        created_by: str,
        files: Sequence[IngestFile],
    ) -> IngestSession:
        """Reserve a session and its ledger under the dataset's lock.

        Args:
            dataset_id: The dataset the revision is being added to.
            manifest_sha256: The content identity of the declared manifest.
            created_by: The principal opening the session.
            files: The upload plan's per-file ledger entries.

        Returns:
            The reserved session, in PREPARING with etag 1.

        Raises:
            ResourceNotFound: If no dataset has ``dataset_id``.
            DatasetLocked: If another session for the dataset is not yet
                terminal, or the dataset's latest committed revision has
                no longer exists.
        """
        if dataset_id not in self._store._datasets and dataset_id not in self._buffer.datasets:
            raise ResourceNotFound(f"dataset does not exist: {dataset_id}")
        open_session = _find_open_ingest_session(
            chain(self._store._sessions.values(), self._buffer.sessions.values()), dataset_id
        )
        if open_session is not None:
            raise DatasetLocked(
                f"dataset already has an open ingest session: {dataset_id}",
                context={
                    "session_id": str(open_session.lease.ingest_id),
                    "state": str(open_session.state),
                    "expires_at": open_session.lease.expires_at.isoformat(),
                },
            )
        revisions = tuple(chain(self._store._revisions.values(), self._buffer.revisions.values()))
        latest = latest_revision(revisions, dataset_id)
        session = _reserve_ingest_session(
            dataset_id,
            manifest_sha256,
            created_by=created_by,
            number=(latest.number if latest is not None else 0) + 1,
            now=self._store._clock.now(),
        )
        self._buffer.sessions[session.lease.ingest_id] = session
        for file in files:
            self._buffer.files[file.file_id] = LedgerEntry(
                ingest_id=session.lease.ingest_id, file=_reserved_file(file)
            )
        return session

    async def lock_ingest_session(self, session_id: UUID) -> IngestSession:
        """Hold the session mutation lock through the enclosing transaction.

        Args:
            session_id: Session identity to fence.

        Returns:
            The current session under the transaction lock.
        """
        return await self._store.ingest_session(session_id)

    async def freeze_commit(
        self,
        session: IngestSession,
        intent: CommitIntent,
        *,
        expected_etag: int,
    ) -> tuple[IngestSession, CommitIntent]:
        """Freeze the first command and return it for every identical retry.

        Args:
            session: Proposed COMMITTING session.
            intent: Proposed immutable document set.
            expected_etag: Previously observed session version.

        Returns:
            The persisted session and frozen intent.

        Raises:
            PreconditionFailed: If the session is missing, fenced or changed.
        """
        intent.require_session(session)
        key = session.lease.ingest_id
        current = self._store._sessions.get(key)
        existing = self._store._intents.get(key)
        if current is not None and existing is not None:
            existing.require_session(current)
            existing.require_same_command(intent)
            if current.state in {IngestState.COMMITTING, IngestState.COMMITTED}:
                return current, existing
        if (
            current is None
            or current.state is not IngestState.VERIFYING
            or current.etag != expected_etag
        ):
            raise PreconditionFailed(f"ingest commit version conflict: {key}")
        self._buffer.sessions[key] = session
        self._buffer.intents[key] = intent
        return session, intent

    async def update_ingest_session(self, session: IngestSession, *, expected_etag: int) -> None:
        """Persist one state edge, guarded by optimistic concurrency on the session's etag.

        Args:
            session: The session as it should read after the edge.
            expected_etag: The etag the caller last read.

        Raises:
            PreconditionFailed: If no session has ``session.lease.ingest_id``,
                or its stored etag is not ``expected_etag``.
        """
        current = self._store._sessions.get(session.lease.ingest_id)
        if current is None or current.etag != expected_etag:
            raise PreconditionFailed(f"ingest session version conflict: {session.lease.ingest_id}")
        self._buffer.sessions[session.lease.ingest_id] = session

    async def renew_ingest_session(self, session: IngestSession) -> None:
        """Move a session's lease forward, never backward, leaving its state and etag untouched.

        Args:
            session: The session carrying the candidate new lease.

        Raises:
            IngestSessionExpired: If no session has ``session.lease.ingest_id``,
                or it is already terminal.
        """
        current = self._store._sessions.get(session.lease.ingest_id)
        if current is None or current.state in TERMINAL_STATES | {IngestState.RECOVERING}:
            raise IngestSessionExpired(f"ingest session {session.lease.ingest_id} is not renewable")
        renewed_expiry = max(current.lease.expires_at, session.lease.expires_at)
        self._buffer.sessions[session.lease.ingest_id] = replace(
            current, lease=replace(current.lease, expires_at=renewed_expiry)
        )

    async def expire_ingest_session(
        self, session: IngestSession, *, expected_etag: int, now: datetime
    ) -> None:
        """Persist the sweep's ``expire`` edge, fenced on both the etag and the lease.

        Args:
            session: The session as it should read after the edge, already
                advanced to ABORTED.
            expected_etag: The etag the sweep last read.
            now: The instant the sweep is running at.

        Raises:
            PreconditionFailed: If the session is not found, its etag has
                moved, its state is no longer open, or its lease is no
                longer lapsed at ``now``.
        """
        current = self._store._sessions.get(session.lease.ingest_id)
        fenced = (
            current is not None
            and current.etag == expected_etag
            and current.state in _OPEN_INGEST_STATES
            and current.lease.expires_at <= now
        )
        if not fenced:
            raise PreconditionFailed(f"ingest session expiry conflict: {session.lease.ingest_id}")
        self._buffer.sessions[session.lease.ingest_id] = session

    async def update_ingest_file(
        self, ingest_id: UUID, file: IngestFile, *, expected_parts: frozenset[int]
    ) -> None:
        """Persist one ledger step, fenced on the file still being PENDING with expected parts.

        Args:
            ingest_id: The session the file's ledger row belongs to.
            file: The file as it should read after the step.
            expected_parts: The parts the caller last read for this file.

        Raises:
            PreconditionFailed: If no PENDING file has ``file.file_id`` under
                ``ingest_id`` with exactly ``expected_parts`` recorded.
        """
        current = self._store._files.get(file.file_id)
        fenced = (
            current is not None
            and current.ingest_id == ingest_id
            and current.file.state is FileState.PENDING
            and self._store._sessions[ingest_id].state in _OPEN_INGEST_STATES
            and current.file.completed_parts == expected_parts
        )
        if not fenced:
            raise PreconditionFailed(f"ingest file version conflict: {file.file_id}")
        self._buffer.files[file.file_id] = LedgerEntry(ingest_id=ingest_id, file=file)


class InMemoryIngestReader:
    """The ingest half of ``InMemoryHierarchyStore``'s read surface.

    Mixed into ``hierarchy.InMemoryHierarchyStore``, which supplies
    ``_sessions`` and ``_files``.
    """

    _sessions: dict[UUID, IngestSession]
    _files: dict[UUID, LedgerEntry]

    async def ingest_session(self, session_id: UUID) -> IngestSession:
        """Return one session by id, in whatever state it currently holds.

        Args:
            session_id: The session to read.

        Returns:
            The stored session.

        Raises:
            ResourceNotFound: If no session has ``session_id``.
        """
        found = self._sessions.get(session_id)
        if found is None:
            raise ResourceNotFound(f"ingest session does not exist: {session_id}")
        return found

    async def ingest_files(self, session_id: UUID) -> tuple[IngestFile, ...]:
        """Return a session's ledger, one entry per planned file, in manifest order.

        Args:
            session_id: The session whose ledger to read.

        Returns:
            The session's files ordered by path; empty if the session names
            no files or does not exist.
        """
        entries = [entry for entry in self._files.values() if entry.ingest_id == session_id]
        entries.sort(key=lambda entry: entry.file.path)
        return tuple(entry.file for entry in entries)

    async def ingest_file(self, file_id: UUID) -> LedgerEntry:
        """Return one ledger entry together with the id of the session it belongs to.

        Args:
            file_id: The file to read.

        Returns:
            The file's current ledger state and the id of its session.

        Raises:
            ResourceNotFound: If no file has ``file_id``.
        """
        found = self._files.get(file_id)
        if found is None:
            raise ResourceNotFound(f"ingest file does not exist: {file_id}")
        return found

    async def lapsed_ingest_sessions(
        self, now: datetime, *, limit: int
    ) -> tuple[IngestSession, ...]:
        """Return the oldest lapsed, still-open sessions, for the expiry sweep to reap.

        Args:
            now: The instant a session's lease is judged lapsed against.
            limit: The maximum number of sessions to return.

        Returns:
            Up to ``limit`` sessions in PREPARING, UPLOADING or VERIFYING
            whose lease has lapsed at or before ``now``, oldest lease first.
        """
        lapsed = [
            session
            for session in self._sessions.values()
            if session.state in _OPEN_INGEST_STATES and session.lease.expires_at <= now
        ]
        lapsed.sort(key=lambda session: (session.lease.expires_at, session.lease.ingest_id))
        return tuple(lapsed[:limit])


class PostgresIngestWriter:
    """The ingest half of one Postgres transaction's write surface.

    Mixed into ``hierarchy._PostgresTransactionWriter``, which supplies
    ``_connection`` and ``_clock``.
    """

    _connection: asyncpg.Connection
    _clock: Clock

    async def begin_ingest(
        self,
        dataset_id: UUID,
        manifest_sha256: str,
        *,
        created_by: str,
        files: Sequence[IngestFile],
    ) -> IngestSession:
        """Reserve a session and its ledger under the dataset's row lock.

        Args:
            dataset_id: The dataset the revision is being added to.
            manifest_sha256: The content identity of the declared manifest.
            created_by: The principal opening the session.
            files: The upload plan's per-file ledger entries.

        Returns:
            The reserved session, in PREPARING with etag 1.

        Raises:
            ResourceNotFound: If no dataset has ``dataset_id``.
            DatasetLocked: If another session for the dataset is not yet
                terminal, or the dataset's latest committed revision has
                no longer exists.
        """
        connection = self._connection
        if not await _dataset_row_exists(connection, dataset_id):
            raise ResourceNotFound(f"dataset does not exist: {dataset_id}")
        open_session = await _pg_open_ingest_session(connection, dataset_id)
        if open_session is not None:
            raise DatasetLocked(
                f"dataset already has an open ingest session: {dataset_id}",
                context={
                    "session_id": str(open_session["id"]),
                    "state": open_session["state"],
                    "expires_at": open_session["expires_at"].isoformat(),
                },
            )
        number = await _pg_next_revision_number(connection, dataset_id)
        now = self._clock.now()
        session = _reserve_ingest_session(
            dataset_id,
            manifest_sha256,
            created_by=created_by,
            number=number,
            now=now,
        )
        await self._insert_ingest_session_row(session, now)
        await self._insert_ingest_file_rows(session.lease.ingest_id, files)
        return session

    async def _insert_ingest_session_row(self, session: IngestSession, now: datetime) -> None:
        """Insert the session row ``begin_ingest`` just reserved.

        Args:
            session: The session to insert, fully formed.
            now: The single instant ``begin_ingest`` reserved this session
                at - stamped onto both ``created_at`` and ``updated_at``, so
                every timestamp this call writes traces back to one read of
                the clock.

        Raises:
            DatasetLocked: If the per-dataset open-session index refuses the
                row - unreachable under the row lock ``begin_ingest`` takes
                first, kept as a backstop against a writer that bypassed it.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
        """
        lease = session.lease
        try:
            await self._connection.execute(
                """
                INSERT INTO ingest_sessions
                    (id, dataset_id, revision_id, revision_number, manifest_sha256, state, etag,
                     expires_at, created_by, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
                """,
                lease.ingest_id,
                lease.dataset_id,
                lease.revision_id,
                lease.revision_number,
                session.manifest_sha256,
                str(session.state),
                session.etag,
                lease.expires_at,
                session.created_by,
                now,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _OPEN_INGEST_SESSION_CONSTRAINT:
                raise
            raise DatasetLocked(
                f"dataset already has an open ingest session: {lease.dataset_id}",
                context={"reason": "concurrent_open_session"},
            ) from exc

    async def _insert_ingest_file_rows(self, ingest_id: UUID, files: Sequence[IngestFile]) -> None:
        """Insert one ledger row per planned file, reserved alongside the session.

        Args:
            ingest_id: The session the files are being reserved for.
            files: The upload plan's per-file ledger entries.
        """
        await self._connection.execute(
            """
            INSERT INTO ingest_files (file_id, ingest_id, path, size, expected_sha256, action,
                                       part_count)
            SELECT * FROM unnest($1::uuid[], $2::uuid[], $3::text[], $4::bigint[], $5::text[],
                                  $6::text[], $7::integer[])
            """,
            [file.file_id for file in files],
            [ingest_id] * len(files),
            [file.path for file in files],
            [file.size for file in files],
            [file.expected_sha256 for file in files],
            [str(file.action) for file in files],
            [file.part_count for file in files],
        )

    async def lock_ingest_session(self, session_id: UUID) -> IngestSession:
        """Hold the session mutation lock through the enclosing transaction.

        Args:
            session_id: Session identity to fence.

        Returns:
            The current session under the transaction lock.

        Raises:
            ResourceNotFound: If the session does not exist.
        """
        row = await self._connection.fetchrow(
            f"SELECT {_INGEST_SESSION_COLUMNS} FROM ingest_sessions WHERE id = $1 FOR UPDATE",
            session_id,
        )
        if row is None:
            raise ResourceNotFound(f"ingest session does not exist: {session_id}")
        return rows.ingest_session(row)

    async def freeze_commit(
        self,
        session: IngestSession,
        intent: CommitIntent,
        *,
        expected_etag: int,
    ) -> tuple[IngestSession, CommitIntent]:
        """Freeze canonical evidence under the session row lock before storage work.

        Args:
            session: Proposed COMMITTING session.
            intent: Proposed canonical command and document set.
            expected_etag: Previously observed session version.

        Returns:
            The persisted session and immutable evidence.

        Raises:
            PreconditionFailed: If the session is missing, fenced or changed.
        """
        intent.require_session(session)
        key = session.lease.ingest_id
        row = await self._connection.fetchrow(
            f"SELECT {_INGEST_SESSION_COLUMNS} FROM ingest_sessions WHERE id = $1 FOR UPDATE", key
        )
        existing = await self._connection.fetchrow(
            "SELECT command, manifest, metadata, committed "
            "FROM ingest_commit_intents WHERE ingest_id = $1",
            key,
        )
        if row is not None and existing is not None:
            frozen = CommitIntent(
                existing["command"],
                existing["manifest"],
                existing["metadata"],
                existing["committed"],
            )
            frozen.require_same_command(intent)
            current = rows.ingest_session(row)
            frozen.require_session(current)
            if current.state in {IngestState.COMMITTING, IngestState.COMMITTED}:
                return current, frozen
        if row is None or row["state"] != "VERIFYING" or row["etag"] != expected_etag:
            raise PreconditionFailed(f"ingest commit version conflict: {key}")
        await self.update_ingest_session(session, expected_etag=expected_etag)
        marker = CommitRecord.decode(intent.committed)
        await self._connection.execute(
            """INSERT INTO ingest_commit_intents
               (ingest_id, command, manifest, metadata, committed, committed_by, committed_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            key,
            intent.command,
            intent.manifest,
            intent.metadata,
            intent.committed,
            marker.committed_by,
            marker.committed_at,
        )
        return session, intent

    async def update_ingest_session(self, session: IngestSession, *, expected_etag: int) -> None:
        """Persist one state edge, guarded by optimistic concurrency on the session's etag.

        Args:
            session: The session as it should read after the edge.
            expected_etag: The etag the caller last read.

        Raises:
            PreconditionFailed: If no session has ``session.lease.ingest_id``,
                or its stored etag is not ``expected_etag``.
        """
        tag = await self._connection.execute(
            """
            UPDATE ingest_sessions SET state = $2, etag = $3, updated_at = $4
            WHERE id = $1 AND etag = $5
            """,
            session.lease.ingest_id,
            str(session.state),
            session.etag,
            self._clock.now(),
            expected_etag,
        )
        if rows.affected_row_count(tag) == 0:
            raise PreconditionFailed(f"ingest session version conflict: {session.lease.ingest_id}")

    async def renew_ingest_session(self, session: IngestSession) -> None:
        """Move a session's lease forward, never backward, leaving its state and etag untouched.

        Args:
            session: The session carrying the candidate new lease.

        Raises:
            IngestSessionExpired: If no session has ``session.lease.ingest_id``,
                or it is already terminal.
        """
        tag = await self._connection.execute(
            f"""
            UPDATE ingest_sessions SET expires_at = GREATEST(expires_at, $2), updated_at = $3
            WHERE id = $1 AND state NOT IN ({_TERMINAL_STATE_NAMES}) AND state <> 'RECOVERING'
            """,
            session.lease.ingest_id,
            session.lease.expires_at,
            self._clock.now(),
        )
        if rows.affected_row_count(tag) == 0:
            raise IngestSessionExpired(f"ingest session {session.lease.ingest_id} is not renewable")

    async def expire_ingest_session(
        self, session: IngestSession, *, expected_etag: int, now: datetime
    ) -> None:
        """Persist the sweep's ``expire`` edge, fenced on both the etag and the lease.

        Args:
            session: The session as it should read after the edge, already
                advanced to ABORTED.
            expected_etag: The etag the sweep last read.
            now: The instant the sweep is running at.

        Raises:
            PreconditionFailed: If the session is not found, its etag has
                moved, its state is no longer open, or its lease is no
                longer lapsed at ``now``.
        """
        tag = await self._connection.execute(
            f"""
            UPDATE ingest_sessions SET state = $2, etag = $3, updated_at = $4
            WHERE id = $1 AND etag = $5 AND state IN ({_OPEN_STATE_NAMES}) AND expires_at <= $4
            """,
            session.lease.ingest_id,
            str(session.state),
            session.etag,
            now,
            expected_etag,
        )
        if rows.affected_row_count(tag) == 0:
            raise PreconditionFailed(f"ingest session expiry conflict: {session.lease.ingest_id}")

    async def update_ingest_file(
        self, ingest_id: UUID, file: IngestFile, *, expected_parts: frozenset[int]
    ) -> None:
        """Persist one ledger step, fenced on the file still being PENDING with expected parts.

        Args:
            ingest_id: The session the file's ledger row belongs to.
            file: The file as it should read after the step.
            expected_parts: The parts the caller last read for this file.

        Raises:
            PreconditionFailed: If no PENDING file has ``file.file_id`` under
                ``ingest_id`` with exactly ``expected_parts`` recorded.
        """
        tag = await self._connection.execute(
            """
            UPDATE ingest_files SET state = $3, completed_parts = $4::jsonb
            WHERE file_id = $1 AND ingest_id = $2 AND state = 'PENDING'
              AND completed_parts = $5::jsonb
              AND EXISTS (SELECT 1 FROM ingest_sessions
                          WHERE id = $2 AND state IN ('PREPARING', 'UPLOADING', 'VERIFYING'))
            """,
            file.file_id,
            ingest_id,
            str(file.state),
            json.dumps(sorted(file.completed_parts)),
            json.dumps(sorted(expected_parts)),
        )
        if rows.affected_row_count(tag) == 0:
            raise PreconditionFailed(f"ingest file version conflict: {file.file_id}")


class PostgresIngestReader:
    """The ingest half of ``PostgresHierarchyStore``'s read surface.

    Mixed into ``hierarchy.PostgresHierarchyStore``, which supplies
    ``_pool``.
    """

    _pool: asyncpg.Pool

    async def ingest_session(self, session_id: UUID) -> IngestSession:
        """Return one session by id, in whatever state it currently holds.

        Args:
            session_id: The session to read.

        Returns:
            The stored session.

        Raises:
            ResourceNotFound: If no session has ``session_id``.
        """
        row = await self._pool.fetchrow(
            f"SELECT {_INGEST_SESSION_COLUMNS} FROM ingest_sessions WHERE id = $1", session_id
        )
        if row is None:
            raise ResourceNotFound(f"ingest session does not exist: {session_id}")
        return rows.ingest_session(row)

    async def ingest_files(self, session_id: UUID) -> tuple[IngestFile, ...]:
        """Return a session's ledger, one entry per planned file, in manifest order.

        Args:
            session_id: The session whose ledger to read.

        Returns:
            The session's files ordered by path; empty if the session names
            no files or does not exist.
        """
        fetched = await self._pool.fetch(
            f"""
            SELECT {_INGEST_FILE_COLUMNS} FROM ingest_files
            WHERE ingest_id = $1 ORDER BY path COLLATE "C"
            """,
            session_id,
        )
        return tuple(rows.ingest_file(row) for row in fetched)

    async def ingest_file(self, file_id: UUID) -> LedgerEntry:
        """Return one ledger entry together with the id of the session it belongs to.

        Args:
            file_id: The file to read.

        Returns:
            The file's current ledger state and the id of its session.

        Raises:
            ResourceNotFound: If no file has ``file_id``.
        """
        row = await self._pool.fetchrow(
            f"SELECT ingest_id, {_INGEST_FILE_COLUMNS} FROM ingest_files WHERE file_id = $1",
            file_id,
        )
        if row is None:
            raise ResourceNotFound(f"ingest file does not exist: {file_id}")
        return LedgerEntry(ingest_id=row["ingest_id"], file=rows.ingest_file(row))

    async def lapsed_ingest_sessions(
        self, now: datetime, *, limit: int
    ) -> tuple[IngestSession, ...]:
        """Return the oldest lapsed, still-open sessions, for the expiry sweep to reap.

        Args:
            now: The instant a session's lease is judged lapsed against.
            limit: The maximum number of sessions to return.

        Returns:
            Up to ``limit`` sessions in PREPARING, UPLOADING or VERIFYING
            whose lease has lapsed at or before ``now``, oldest lease first.
        """
        fetched = await self._pool.fetch(
            f"""
            SELECT {_INGEST_SESSION_COLUMNS} FROM ingest_sessions
            WHERE state IN ({_OPEN_STATE_NAMES}) AND expires_at <= $1
            ORDER BY expires_at, id LIMIT $2
            """,
            now,
            limit,
        )
        return tuple(rows.ingest_session(row) for row in fetched)
