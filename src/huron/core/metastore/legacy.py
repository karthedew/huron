"""Narrow schema-0010 inventory import and audited ingest-session terminalization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from . import rows

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    import asyncpg

    from huron.core.catalog.types import Dataset, Organization, Project
    from huron.core.raw.paths import RevisionPath
    from huron.core.raw.types import RevisionRecord


class PostgresLegacyMaintenance:
    """Resolve legacy rows only after the core supplies a complete fenced inventory."""

    def __init__(self, pool: asyncpg.Pool, now: Callable[[], datetime]) -> None:
        """Bind maintenance persistence and its injected audit clock.

        Args:
            pool: Separately authenticated cutover connection pool.
            now: Audit clock supplied by application wiring.
        """
        self._pool = pool
        self._now = now

    async def generation_records(self) -> tuple[Organization | Project | Dataset, ...]:
        """Read every acknowledged hierarchy generation under the legacy schema contract.

        Returns:
            Exact organization, project and dataset records, including empty entities.
        """
        async with self._pool.acquire() as connection:
            await _require_legacy(connection)
            organizations = await connection.fetch("SELECT * FROM organizations ORDER BY id")
            projects = await connection.fetch("SELECT * FROM projects ORDER BY id")
            datasets = await connection.fetch("SELECT * FROM datasets ORDER BY id")
        return (
            *(rows.organization(row) for row in organizations),
            *(rows.project(row) for row in projects),
            *(rows.dataset(row) for row in datasets),
        )

    async def revision_paths(self) -> tuple[str, ...]:
        """List every recorded envelope, including absent physical directories.

        Returns:
            Logical legacy revision paths in deterministic order.
        """
        async with self._pool.acquire() as connection:
            await _require_legacy(connection)
            return tuple(
                str(row["revision_path"])
                for row in await connection.fetch(
                    "SELECT revision_path FROM dataset_revisions ORDER BY revision_path"
                )
            )

    async def lookup(self, identity: RevisionPath) -> RevisionRecord | None:
        """Require existing exact ancestry before trusting or importing a revision identity.

        Args:
            identity: Full path identity supplied by the catalog parser.

        Returns:
            Existing trusted record, or None for an unrecorded final envelope.

        Raises:
            ValueError: If parents are missing or revision identities collide.
        """
        async with self._pool.acquire() as connection:
            await _require_legacy(connection)
            valid = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM datasets d JOIN projects p ON p.id=d.project_id "
                "JOIN organizations o ON o.id=p.organization_id WHERE d.id=$1 AND d.slug=$2 "
                "AND p.id=$3 AND p.slug=$4 AND o.id=$5 AND o.slug=$6)",
                identity.dataset_id,
                identity.dataset_slug,
                identity.project_id,
                identity.project_slug,
                identity.org_id,
                identity.org_slug,
            )
            if not valid:
                raise ValueError("legacy revision parents are missing or inconsistent")
            records = await connection.fetch(
                "SELECT * FROM dataset_revisions WHERE id=$1 OR "
                "(dataset_id=$2 AND revision_number=$3)",
                identity.revision_id,
                identity.dataset_id,
                identity.revision_number,
            )
            if len(records) > 1:
                raise ValueError("legacy revision identities collide")
            return rows.revision_record(records[0]) if records else None

    async def resolve(
        self,
        actor: str,
        root_id: UUID,
        run_id: UUID,
        revisions: tuple[tuple[RevisionRecord, tuple[str, ...]], ...],
    ) -> None:
        """Import trusted inventory and terminalize sessions atomically with audit and findings.

        Args:
            actor: Externally authenticated maintenance actor.
            root_id: Authenticated storage root identity.
            run_id: Idempotent cutover operation identity.
            revisions: Complete inventory with trustworthy records and finding codes.
        """
        instant = self._now()
        async with self._pool.acquire() as connection, connection.transaction():
            await _require_legacy(connection)
            sessions = await connection.fetch(
                "SELECT * FROM ingest_sessions WHERE state NOT IN "
                "('COMMITTED','ABORTED','FAILED') FOR UPDATE"
            )
            for record, findings in revisions:
                await _import_revision(connection, record, findings)
                await _findings(connection, root_id, run_id, record, findings, instant)
                await _audit(
                    connection,
                    actor,
                    root_id,
                    run_id,
                    "dataset_revision",
                    record.id,
                    {"verification": "DEGRADED" if findings else "VERIFIED"},
                    instant,
                )
            by_identity = {record.id: (record, findings) for record, findings in revisions}
            for session in sessions:
                state = _session_outcome(session, by_identity)
                await connection.execute(
                    "UPDATE ingest_sessions SET state=$2, etag=etag+1, updated_at=$3 WHERE id=$1",
                    session["id"],
                    state,
                    instant,
                )
                await _audit(
                    connection,
                    actor,
                    root_id,
                    run_id,
                    "ingest_session",
                    session["id"],
                    {
                        "state": state,
                        "reason": "VERIFIED_FINAL" if state == "COMMITTED" else "NO_VERIFIED_FINAL",
                    },
                    instant,
                )


async def _require_legacy(connection: asyncpg.Connection) -> None:
    if (
        await connection.fetchval("SELECT version_num FROM alembic_version")
        != "0010_independent_raw"
    ):
        raise ValueError("legacy maintenance requires exactly schema 0010_independent_raw")


async def _import_revision(
    connection: asyncpg.Connection, record: RevisionRecord, findings: tuple[str, ...]
) -> None:
    await connection.execute(
        "INSERT INTO dataset_revisions(id,dataset_id,revision_number,manifest_sha256,"
        "metadata_sha256,revision_path,file_count,total_bytes,state,committed_by,committed_at) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(id) DO NOTHING",
        record.id,
        record.dataset_id,
        record.number,
        record.manifest_sha256,
        record.metadata_sha256,
        record.revision_path,
        record.file_count,
        record.total_bytes,
        "DEGRADED" if findings else "COMMITTED",
        record.committed_by,
        record.committed_at,
    )
    existing = await connection.fetchrow(
        "SELECT * FROM dataset_revisions WHERE id=$1 FOR UPDATE", record.id
    )
    if existing is None or rows.revision_record(existing) != record:
        raise ValueError("legacy revision changed during maintenance import")
    if findings:
        await connection.execute(
            "UPDATE dataset_revisions SET state='DEGRADED' WHERE id=$1", record.id
        )


def _session_outcome(
    session: asyncpg.Record,
    revisions: dict[UUID, tuple[RevisionRecord, tuple[str, ...]]],
) -> str:
    observed = revisions.get(session["revision_id"])
    if observed is not None:
        record, findings = observed
        if (record.dataset_id, record.number, record.manifest_sha256) != (
            session["dataset_id"],
            session["revision_number"],
            session["manifest_sha256"],
        ):
            raise ValueError("legacy final and session identity disagree")
        return "COMMITTED" if session["state"] == "COMMITTING" and not findings else "FAILED"
    if any(
        (record.dataset_id, record.number) == (session["dataset_id"], session["revision_number"])
        for record, _ in revisions.values()
    ):
        raise ValueError("legacy session claims an ambiguous final revision number")
    return "FAILED"


async def _findings(
    connection: asyncpg.Connection,
    root_id: UUID,
    run_id: UUID,
    record: RevisionRecord,
    findings: tuple[str, ...],
    instant: datetime,
) -> None:
    for code in findings:
        await connection.execute(
            "INSERT INTO reconciliation_findings(id,code,severity,path,subject_id,detail,found_at) "
            "VALUES($1,$2,'ERROR',$3,$4,$5::jsonb,$6) ON CONFLICT(id) DO NOTHING",
            uuid5(run_id, f"finding:{record.id}:{code}"),
            code,
            record.revision_path,
            record.id,
            json.dumps({"run_id": str(run_id), "root_id": str(root_id)}),
            instant,
        )


async def _audit(
    connection: asyncpg.Connection,
    actor: str,
    root_id: UUID,
    run_id: UUID,
    subject_kind: str,
    subject_id: UUID,
    outcome: dict[str, str],
    instant: datetime,
) -> None:
    await connection.execute(
        "INSERT INTO audit_events(id,kind,actor,subject_kind,subject_id,payload,created_at) "
        "VALUES($1,'integrity.cutover',$2,$3,$4,$5::jsonb,$6) "
        "ON CONFLICT(id) DO NOTHING",
        uuid5(run_id, f"{subject_kind}:{subject_id}"),
        actor,
        subject_kind,
        subject_id,
        json.dumps({"run_id": str(run_id), "root_id": str(root_id), **outcome}),
        instant,
    )
