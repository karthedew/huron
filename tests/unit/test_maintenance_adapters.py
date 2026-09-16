"""Maintenance SQL boundaries reject incomplete exclusion and ambiguous legacy records."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import asyncpg
import pytest

from huron.core.raw.types import RevisionRecord
from huron.core.raw.paths import parse_revision_dir
from huron.core.metastore.legacy import PostgresLegacyMaintenance
from huron.core.metastore.maintenance import PostgresRoleExclusion
from tests.unit.test_lakectl_wiring import IDENTITY, EmptyDatabaseBoundary
from tests.unit.test_legacy_verification import legacy as legacy
from tests.unit.test_legacy_verification import legacy_records

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Fence:
    """The three attributes the adapter reads from a receipt: pkg's structural ``DatabaseFence``."""

    database: str = IDENTITY
    old_roles: tuple[str, ...] = ("old_app",)
    new_role: str = "new_app"


class RoleDatabaseBoundary(EmptyDatabaseBoundary):
    """Inject externally observed SQL role/session facts independently of the exclusion adapter."""

    def __init__(self) -> None:
        super().__init__()
        self.safe = True
        self.admitted = False
        self.effective = False
        self.stopped = True
        self.queries: list[str] = []
        self.statements: list[str] = []

    async def fetchval(self, query: str, *arguments: object) -> object:
        """Route the identity probe and injected faults to the shared seam, then role facts."""
        self.queries.append(query)
        if self.failure is not None or "pg_control_system" in query:
            return await super().fetchval(query, *arguments)
        if "SELECT NOT (rolsuper" in query:
            return self.safe
        if "rolcanlogin" in query:
            return self.admitted
        return self.effective

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        """Supply termination results and effective grant inventory."""
        if "pg_terminate_backend" in query:
            return [{"stopped": self.stopped}]
        if "pg_auth_members" in query:
            return [{"rolname": "inherited_writer"}]
        return [{"nspname": 'quoted"schema'}]

    async def execute(self, query: str, *arguments: object) -> str:
        """Capture changes reaching the database boundary."""
        self.statements.append(query)
        return "REVOKE"


@pytest.mark.parametrize(
    "old,new", [((), "new"), (("old",), "old"), (("old", "old"), "new"), (("unsafe-role",), "new")]
)
async def test_role_adapter_refuses_ambiguous_or_unquotable_application_identities(
    old: tuple[str, ...],
    new: str,
) -> None:
    """Invalid role sets fail before any SQL mutation reaches the connection boundary."""
    database = RoleDatabaseBoundary()
    with pytest.raises(ValueError):
        await PostgresRoleExclusion(database).exclude(Fence(old_roles=old, new_role=new))
    assert not database.statements
    assert not database.queries


@pytest.mark.parametrize(
    "field,message",
    [
        ("safe", "administrative or owns"),
        ("stopped", "termination was not confirmed"),
        ("admitted", "login or session fence"),
        ("effective", "effective application access"),
    ],
)
async def test_role_adapter_refuses_unconfirmed_external_exclusion(
    field: str, message: str
) -> None:
    """Every externally observed escape prevents the adapter from claiming a complete fence."""
    database = RoleDatabaseBoundary()
    setattr(database, field, field in {"admitted", "effective"})
    with pytest.raises(ValueError, match=message):
        await PostgresRoleExclusion(database).exclude(Fence())


async def test_role_adapter_identifies_the_primary_and_refuses_an_empty_identity() -> None:
    """The primary's identity is observed directly, with no role read or altered."""
    database = RoleDatabaseBoundary()
    assert await PostgresRoleExclusion(database).identify() == IDENTITY
    assert len(database.queries) == 1
    assert "pg_control_system" in database.queries[0]
    assert "NOT pg_is_in_recovery()" in database.queries[0]
    database.identity = None
    with pytest.raises(ValueError, match="is not a primary"):
        await PostgresRoleExclusion(database).identify()
    database.failure = asyncpg.PostgresError("private")
    with pytest.raises(asyncpg.PostgresError):
        await PostgresRoleExclusion(database).identify()


@pytest.mark.parametrize("method", ["exclude", "check"])
async def test_role_adapter_refuses_a_foreign_fence_before_any_role_change(method: str) -> None:
    """A fence naming another database is refused before any role read or mutation."""
    database = RoleDatabaseBoundary()
    with pytest.raises(ValueError, match="database identity differs from the fence"):
        await getattr(PostgresRoleExclusion(database), method)(Fence(database="1/16384/other"))
    assert database.statements == []
    assert len(database.queries) == 1
    assert "pg_control_system" in database.queries[0]


async def test_role_adapter_observes_identity_before_every_role_statement() -> None:
    """The identity is the first query in both ``exclude`` and ``check``."""
    database = RoleDatabaseBoundary()
    await PostgresRoleExclusion(database).exclude(Fence())
    assert "pg_control_system" in database.queries[0]
    assert database.statements[0] == 'ALTER ROLE "old_app" NOLOGIN'
    assert sum("pg_control_system" in query for query in database.queries) == 2
    database.queries.clear()
    await PostgresRoleExclusion(database).check(Fence())
    assert "pg_control_system" in database.queries[0]


class LegacyDatabaseBoundary(EmptyDatabaseBoundary):
    """Supply exact external legacy rows and capture observable persisted outcomes."""

    def __init__(self, record: RevisionRecord) -> None:
        super().__init__()
        self.schema = "0010_independent_raw"
        self.parents = True
        self.records = [self.revision_row(record)]
        self.imported: dict[str, object] | None = self.records[0]
        self.sessions: list[dict[str, object]] = []
        self.writes: list[tuple[str, tuple[object, ...]]] = []

    @staticmethod
    def revision_row(record: RevisionRecord) -> dict[str, object]:
        """Encode the exact legacy SQL row shape."""
        document = asdict(record)
        document["revision_number"] = document.pop("number")
        return document

    async def fetchval(self, query: str, *arguments: object) -> object:
        """Supply schema and parent-identity observations."""
        return self.schema if "version_num" in query else self.parents

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, object]]:
        """Supply acknowledged hierarchy, revision and session rows."""
        organization, project, dataset = (asdict(item) for item in legacy_records())
        project["classification_default"] = project.pop("data_classification")
        hierarchy = {"organizations": organization, "projects": project, "datasets": dataset}
        for table, document in hierarchy.items():
            if f"FROM {table} ORDER" in query:
                return [document]
        return self.sessions if "FROM ingest_sessions" in query else self.records

    async def fetchrow(self, query: str, *arguments: object) -> dict[str, object] | None:
        """Observe the actual row remaining after conflict-aware insertion."""
        return self.imported

    async def execute(self, query: str, *arguments: object) -> str:
        """Capture persisted session, finding and audit outcomes."""
        self.writes.append((query, arguments))
        return "UPDATE 1"


async def test_legacy_adapter_reads_exact_hierarchy_paths_and_trusted_records(
    legacy: tuple[object, str, RevisionRecord],
) -> None:
    """The narrow adapter maps acknowledged hierarchy and exact revision identity from SQL rows."""
    record = legacy[2]
    database = LegacyDatabaseBoundary(record)
    adapter = PostgresLegacyMaintenance(database, lambda: datetime.now(UTC))
    assert await adapter.generation_records() == legacy_records()
    assert await adapter.revision_paths() == (record.revision_path,)
    identity = parse_revision_dir(PurePosixPath("/data"), PurePosixPath(record.revision_path))
    assert await adapter.lookup(identity) == record
    database.records = []
    assert await adapter.lookup(identity) is None
    database.records = [database.revision_row(record)] * 2
    with pytest.raises(ValueError, match="identities collide"):
        await adapter.lookup(identity)
    database.parents = False
    with pytest.raises(ValueError, match="parents"):
        await adapter.lookup(identity)
    database.schema = "0011"
    with pytest.raises(ValueError, match="exactly schema"):
        await adapter.revision_paths()


@pytest.mark.parametrize(
    "case",
    ["verified", "corrupt", "uploading", "absent", "mismatch", "ambiguous", "changed", "missing"],
)
async def test_legacy_resolution_preserves_findings_and_refuses_identity_races(
    legacy: tuple[object, str, RevisionRecord],
    case: str,
) -> None:
    """Only exact healthy committing sessions succeed; ambiguous identity blocks import."""
    record = legacy[2]
    database = LegacyDatabaseBoundary(record)
    session = {
        "id": UUID(int=20),
        "revision_id": record.id,
        "dataset_id": record.dataset_id,
        "revision_number": record.number,
        "manifest_sha256": record.manifest_sha256,
        "state": "UPLOADING" if case == "uploading" else "COMMITTING",
    }
    if case == "mismatch":
        session["manifest_sha256"] = "c" * 64
    if case in {"absent", "ambiguous"}:
        session["revision_id"] = UUID(int=21)
        if case == "absent":
            session["revision_number"] = 2
    if case == "missing":
        database.imported = None
    if case == "changed":
        database.imported = {**database.revision_row(record), "manifest_sha256": "c" * 64}
    database.sessions = [session]
    adapter = PostgresLegacyMaintenance(database, lambda: datetime(2026, 1, 1, tzinfo=UTC))
    revisions = ((record, ("PAYLOAD_CORRUPT",) if case == "corrupt" else ()),)
    if case in {"mismatch", "ambiguous", "missing", "changed"}:
        with pytest.raises(ValueError):
            await adapter.resolve("local:0", UUID(int=1), UUID(int=2), revisions)
    else:
        await adapter.resolve("local:0", UUID(int=1), UUID(int=2), revisions)
        states = [
            arguments[1]
            for query, arguments in database.writes
            if "UPDATE ingest_sessions" in query
        ]
        assert states == ["COMMITTED" if case == "verified" else "FAILED"]
        audits = [
            arguments for query, arguments in database.writes if "INSERT INTO audit_events" in query
        ]
        assert len(audits) == 2
        findings = [
            arguments
            for query, arguments in database.writes
            if "INSERT INTO reconciliation_findings" in query
        ]
        assert len(findings) == int(case == "corrupt")
