"""Shared public-store scenarios for lake persistence adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Protocol
from uuid import UUID, uuid5

import pytest

from huron.core.foundation.canonical import content_identity
from huron.core.foundation.errors import IdempotencyKeyReused
from huron.core.foundation.paging import Window
from huron.core.foundation.retry import IdempotencyClaim, Replay, request_sha256
from huron.core.lake.audit import (
    AuditEntry,
    AuditObject,
    AuditRecord,
    CatalogCreated,
    CollectionCreated,
)
from huron.core.lake.errors import SchemaInvalid, SchemaVersionExists
from huron.core.lake.types import MetadataSchemaRecord
from huron.core.metastore.lake.memory import (
    IntegrityViolation,
    LdapGroupRow,
    RoleMappingRow,
    SigningKeyRow,
)
from huron.core.security.broker import CatalogRef, Grant, Grants, Role, SigningKeyRecord
from huron.schema.metadata import DRAFT_2020_12
from tests.lake_tokens import TEST_EPOCH, TEST_RECORD

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from huron.core.lake.ports import LakeStore
    from huron.core.metastore.lake import InMemoryLakeStore
    from tests.unit.support import FakeClock


async def store_root_scenario(store: LakeStore) -> None:
    """Readiness answers None and a transaction may exit without writes."""
    assert await store.ping() is None
    async with store.transaction():
        pass


async def transaction_error_scenario(store: LakeStore) -> None:
    """A transaction propagates the original exception, leaving the store usable."""
    failure = ValueError("transaction failed")
    with pytest.raises(ValueError) as caught:
        async with store.transaction():
            raise failure
    assert caught.value is failure
    async with store.transaction():
        pass


class LakeSeed(Protocol):
    """Populate store scenarios without requiring domain writer ports."""

    async def ldap_group(self, name: str, gid: int) -> None:
        """Register a directory group before mapping it."""
        ...

    async def role_mapping(self, group: str, catalog: CatalogRef | None, role: Role) -> None:
        """Seed one valid scoped mapping, refusing invalid role/scope combinations."""
        ...

    async def remove_role_mapping(self, group: str, catalog: CatalogRef | None) -> None:
        """Remove the mapping for one group and scope, if present."""
        ...

    async def signing_key(self, record: SigningKeyRecord, created_by: str) -> None:
        """Seed the public registration and its creator."""
        ...


class MemorySeed:
    """Write committed fake rows for adapter-independent scenarios."""

    def __init__(self, store: InMemoryLakeStore) -> None:
        self._tables = store.tables

    async def ldap_group(self, name: str, gid: int) -> None:
        """Register the named group's fixed directory identifier."""
        self._tables.ldap_groups[name] = LdapGroupRow(name, gid, TEST_EPOCH)

    async def role_mapping(self, group: str, catalog: CatalogRef | None, role: Role) -> None:
        """Require a directory row and a valid scope before storing a mapping."""
        Grant(role, catalog)
        if group not in self._tables.ldap_groups:
            raise ValueError("Mapping requires a registered directory group")
        scope = "catalog" if role.catalog_scoped else "organization"
        key = (group, catalog.id if catalog is not None else None)
        self._tables.group_role_map[key] = RoleMappingRow(
            group, catalog, role.code, scope, TEST_EPOCH, "seed"
        )

    async def remove_role_mapping(self, group: str, catalog: CatalogRef | None) -> None:
        """Remove only the named group's mapping in the requested scope."""
        self._tables.group_role_map.pop((group, catalog.id if catalog is not None else None), None)

    async def signing_key(self, record: SigningKeyRecord, created_by: str) -> None:
        """Store each public-key member and interval without private material."""
        key = record.key
        self._tables.signing_keys[key.kid] = SigningKeyRow(
            key.kid,
            key.alg,
            key.members,
            record.private_ref,
            record.active_from,
            record.retired_at,
            TEST_EPOCH,
            created_by,
        )


async def role_mapping_scenario(store: LakeStore, seed: LakeSeed) -> None:
    """Group unions preserve catalog identity and isolate authority across catalogs."""
    first = CatalogRef(UUID(int=1), "heliophysics")
    second = CatalogRef(UUID(int=2), "genomics")
    unrelated = CatalogRef(UUID(int=3), "other")
    for gid, group in enumerate(("readers", "owners", "administrators", "unmapped"), 100):
        await seed.ldap_group(group, gid)
    await seed.role_mapping("readers", first, Role.CATALOG_READER)
    await seed.role_mapping("readers", second, Role.CATALOG_CONTRIBUTOR)
    await seed.role_mapping("owners", first, Role.CATALOG_OWNER)
    await seed.role_mapping("administrators", None, Role.ADMINISTRATOR)
    assert await store.roles_for_groups(frozenset()) == ()
    assert await store.roles_for_groups(frozenset({"unknown", "unmapped"})) == ()
    rows = await store.roles_for_groups(frozenset({"readers", "owners", "unknown"}))
    assert set(rows) == {
        Grant(Role.CATALOG_READER, first),
        Grant(Role.CATALOG_CONTRIBUTOR, second),
        Grant(Role.CATALOG_OWNER, first),
    }
    authority = Grants("scientist", rows)
    assert authority.role_on(first) == Role.CATALOG_OWNER
    assert authority.role_on(second) == Role.CATALOG_CONTRIBUTOR
    assert authority.role_on(unrelated) is None
    assert not authority.readable().every
    assert authority.readable().ids == {first.id, second.id}
    admin = await store.roles_for_groups(frozenset({"administrators"}))
    assert admin == (Grant(Role.ADMINISTRATOR, None),)
    assert Grants("administrator", admin).readable().every
    await seed.role_mapping("readers", first, Role.CATALOG_CONTRIBUTOR)
    assert set(await store.roles_for_groups(frozenset({"readers"}))) == {
        Grant(Role.CATALOG_CONTRIBUTOR, first),
        Grant(Role.CATALOG_CONTRIBUTOR, second),
    }

    await seed.remove_role_mapping("readers", first)
    await seed.remove_role_mapping("readers", first)
    assert set(await store.roles_for_groups(frozenset({"readers", "owners"}))) == {
        Grant(Role.CATALOG_CONTRIBUTOR, second),
        Grant(Role.CATALOG_OWNER, first),
    }
    await seed.remove_role_mapping("administrators", None)
    assert await store.roles_for_groups(frozenset({"administrators"})) == ()


async def invalid_role_scope_scenario(store: LakeStore, seed: LakeSeed) -> None:
    """Invalid mapping scopes are refused without leaving any authority behind."""
    await seed.ldap_group("invalid", 100)
    for role in Role:
        catalog = CatalogRef(UUID(int=1), "heliophysics") if role == Role.ADMINISTRATOR else None
        with pytest.raises(ValueError):
            await seed.role_mapping("invalid", catalog, role)
        assert await store.roles_for_groups(frozenset({"invalid"})) == ()


async def signing_key_scenario(store: LakeStore, seed: LakeSeed) -> None:
    """Retirement filtering is exclusive, includes open intervals and orders activations."""
    assert await store.unexpired(TEST_EPOCH) == ()
    step = timedelta(seconds=1)
    retired = replace(TEST_RECORD, retired_at=TEST_EPOCH + step)
    open_record = replace(
        TEST_RECORD,
        key=replace(TEST_RECORD.key, kid="open"),
        private_ref="open.pem",
        active_from=TEST_EPOCH + 3 * step,
    )
    later = replace(
        TEST_RECORD,
        key=replace(TEST_RECORD.key, kid="later"),
        private_ref="later.pem",
        active_from=TEST_EPOCH + step,
        retired_at=TEST_EPOCH + 2 * step,
    )
    for row in (open_record, later, retired):
        await seed.signing_key(row, "registrar")
    assert await store.unexpired(TEST_EPOCH) == (retired, later, open_record)
    assert await store.unexpired(TEST_EPOCH + step) == (later, open_record)
    assert await store.unexpired(TEST_EPOCH + 2 * step) == (open_record,)
    assert await store.unexpired(TEST_EPOCH + 4 * step) == (open_record,)


class CommittedAudit(Protocol):
    """Read the committed audit log, which no lake port exposes whole."""

    async def records(self) -> list[AuditRecord]:
        """Return every committed entry in ascending id order."""
        ...


class MemoryCommittedAudit:
    """Read the fake's committed audit rows."""

    def __init__(self, store: InMemoryLakeStore) -> None:
        self._tables = store.tables

    async def records(self) -> list[AuditRecord]:
        """Return the fake's rows in id order."""
        return [self._tables.audit_log[row_id] for row_id in sorted(self._tables.audit_log)]


class ConstraintRefusal(Protocol):
    """Expect a write to be refused by the named PostgreSQL constraint."""

    def __call__(self, constraint: str) -> AbstractContextManager[object]:
        """Return a context that passes only when that constraint refuses its block."""
        ...


def memory_refusal(constraint: str) -> AbstractContextManager[object]:
    """Expect the fake's backstop for the named constraint."""
    return pytest.raises(IntegrityViolation, check=lambda error: error.constraint == constraint)


@dataclass(frozen=True, slots=True, kw_only=True)
class UnseededEvent:
    """An event whose pair the audit vocabulary does not hold."""

    ACTION: ClassVar = "frobnicate"
    OBJECT: ClassVar = AuditObject.CATALOG
    KEY: ClassVar = "catalog"

    catalog: UUID


def catalog_created(name: str) -> AuditEntry:
    """Record the creation of a catalog with the given name."""
    return AuditEntry(
        TEST_EPOCH, "scientist", CatalogCreated(catalog=UUID(int=1), name=name, config_version=1)
    )


async def audit_commit_scenario(store: LakeStore, audit: CommittedAudit) -> None:
    """Entries appear exactly as encoded when their transaction commits, in call order."""
    first, second, third = (catalog_created(name) for name in ("first", "second", "third"))
    async with store.transaction() as tx:
        await tx.append_audit([first, second])
        await tx.append_audit([third])
        assert await audit.records() == []
    records = await audit.records()
    assert [(r.at, r.actor, r.action, r.object_type) for r in records] == [
        (TEST_EPOCH, "scientist", "create", "catalog")
    ] * 3
    assert [(r.object_id, r.catalog_id, r.reason) for r in records] == [
        (str(UUID(int=1)), UUID(int=1), None)
    ] * 3
    assert [r.detail for r in records] == [entry.detail() for entry in (first, second, third)]
    assert records[0].id < records[1].id < records[2].id
    async with store.transaction() as tx:
        await tx.append_audit([catalog_created("fourth")])
    assert (await audit.records())[-1].id > records[-1].id


async def audit_rollback_scenario(store: LakeStore, audit: CommittedAudit) -> None:
    """A raising block discards its entries and an empty append is refused."""
    failure = ValueError("abort")
    with pytest.raises(ValueError) as caught:
        async with store.transaction() as tx:
            await tx.append_audit([catalog_created("discarded")])
            raise failure
    assert caught.value is failure
    with pytest.raises(ValueError, match="at least one entry"):
        async with store.transaction() as tx:
            await tx.append_audit([])
    assert await audit.records() == []


async def audit_commit_order_scenario(store: LakeStore, audit: CommittedAudit) -> None:
    """Ids follow commit order even when the later commit staged its entry first."""
    staged, release = asyncio.Event(), asyncio.Event()

    async def later() -> None:
        async with store.transaction() as tx:
            await tx.append_audit([catalog_created("later")])
            staged.set()
            await release.wait()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        tasks.create_task(later())
        await staged.wait()
        async with store.transaction() as tx:
            await tx.append_audit([catalog_created("earlier")])
        release.set()
    assert [r.detail["name"] for r in await audit.records()] == ["earlier", "later"]


async def audit_constraint_scenario(
    store: LakeStore, audit: CommittedAudit, refused: ConstraintRefusal
) -> None:
    """An unseeded pair and a catalog-less collection entry are refused, writing nothing."""
    unseeded = AuditEntry(TEST_EPOCH, "scientist", UnseededEvent(catalog=UUID(int=1)))
    orphan = AuditEntry(
        TEST_EPOCH,
        "scientist",
        CollectionCreated(collection=UUID(int=2), catalog=None, version=1, config_version=1),
    )
    for entry, constraint in [
        (unseeded, "audit_log_vocabulary"),
        (orphan, "audit_log_collection_has_catalog"),
    ]:
        with refused(constraint):
            async with store.transaction() as tx:
                await tx.append_audit([catalog_created("valid"), entry])
    assert await audit.records() == []


async def claim_replay_scenario(store: LakeStore) -> None:
    """The same fingerprint replays the receipt; another fingerprint is refused."""
    claim = IdempotencyClaim("scientist", "create-helio", request_sha256("catalog", "helio"))
    replay = Replay("catalog", UUID(int=1))
    async with store.transaction() as tx:
        assert await tx.claim(claim) is None
        assert await tx.claim(claim) is None
        await tx.remember(claim, replay)
        assert await tx.claim(claim) == replay
    async with store.transaction() as tx:
        assert await tx.claim(claim) == replay
        with pytest.raises(IdempotencyKeyReused):
            await tx.claim(replace(claim, request_sha256=request_sha256("catalog", "geo")))
    async with store.transaction() as tx:
        assert await tx.claim(replace(claim, principal="colleague")) is None
        assert await tx.claim(replace(claim, key="create-geo")) is None


async def claim_expiry_scenario(store: LakeStore, clock: FakeClock, replay: Replay) -> None:
    """A claim binds its key for 24 hours whatever its receipt, then another replaces it."""
    claim = IdempotencyClaim("scientist", "retry", request_sha256(replay.kind, "first"))
    other = replace(claim, request_sha256=request_sha256(replay.kind, "second"))
    async with store.transaction() as tx:
        await tx.claim(claim)
        await tx.remember(claim, replay)
    clock.advance(timedelta(hours=24) - timedelta(microseconds=1))
    async with store.transaction() as tx:
        with pytest.raises(IdempotencyKeyReused):
            await tx.claim(other)
    clock.advance(timedelta(microseconds=1))
    async with store.transaction() as tx:
        assert await tx.claim(other) is None
    async with store.transaction() as tx:
        with pytest.raises(IdempotencyKeyReused):
            await tx.claim(claim)


async def claim_rollback_scenario(store: LakeStore) -> None:
    """A rolled-back claim leaves no row, so the key is free for another request."""
    claim = IdempotencyClaim("scientist", "retry", request_sha256("catalog", "first"))
    with pytest.raises(ValueError, match="abort"):
        async with store.transaction() as tx:
            await tx.claim(claim)
            await tx.remember(claim, Replay("catalog", UUID(int=1)))
            raise ValueError("abort")
    async with store.transaction() as tx:
        other = replace(claim, request_sha256=request_sha256("catalog", "second"))
        assert await tx.claim(other) is None


SCHEMA_IDS = UUID("0195f3a2-0000-7000-8000-000000000000")


def schema_record(
    name: str = "org",
    version: int = 1,
    *,
    extends: MetadataSchemaRecord | None = None,
    title: str | None = None,
    **changes: Any,
) -> MetadataSchemaRecord:
    """Build a valid version row with a deterministic id; `changes` override its columns."""
    title = title or f"{name} {version}"
    document = {"$schema": DRAFT_2020_12, "type": "object", "title": title}
    values: dict[str, Any] = {
        "id": uuid5(SCHEMA_IDS, f"{name}/{version}/{title}"),
        "name": name,
        "version": version,
        "extends_id": None if extends is None else extends.id,
        "document": document,
        "sha256": content_identity(document),
        "created_at": TEST_EPOCH,
        "created_by": "administrator",
    }
    return MetadataSchemaRecord(**(values | changes))


async def insert_schemas(store: LakeStore, *records: MetadataSchemaRecord) -> None:
    """Insert versions in one committed transaction."""
    async with store.transaction() as tx:
        for record in records:
            await tx.insert_schema(record)


async def schema_read_scenario(store: LakeStore) -> None:
    """Committed versions read back by reference, id and series; pending ones stay private."""
    base = schema_record()
    assert await store.by_ref("org", 1) is None
    assert await store.latest("org") is None
    async with store.transaction() as tx:
        await tx.insert_schema(base)
        await tx.insert_schema(newer := schema_record(version=2))
        assert await store.by_id(base.id) is None
    extension = schema_record("heliophysics", extends=base)
    await insert_schemas(store, extension)
    assert await store.by_ref("org", 1) == base
    assert await store.by_ref("org", 3) is None
    assert await store.by_ref("geology", 1) is None
    assert await store.by_id(extension.id) == extension
    assert await store.by_id(UUID(int=0)) is None
    assert await store.latest("org") == newer
    assert await store.latest("heliophysics") == extension
    assert await store.latest("geology") is None
    with pytest.raises(ValueError, match="abort"):
        async with store.transaction() as tx:
            await tx.insert_schema(schema_record(version=3))
            raise ValueError("abort")
    assert await store.latest("org") == newer


async def schema_page_scenario(store: LakeStore) -> None:
    """Versions page by `(name, version)`: names in code-point order, versions numerically."""
    bases = [schema_record(version=version) for version in range(1, 11)]
    await insert_schemas(store, *bases)
    names = ["helio_x", "heliophysics", "helio", "helio-x"]
    await insert_schemas(store, *(schema_record(name, extends=bases[0]) for name in names))
    expected = [(name, 1) for name in ("helio", "helio-x", "helio_x", "heliophysics")]
    expected += [("org", version) for version in range(1, 11)]
    seen: list[tuple[str, int]] = []
    after = None
    while True:
        window = await store.schemas(after, 4)
        seen += [(record.name, record.version) for record in window.items]
        if not window.has_more:
            break
        after = seen[-1]
    assert seen == expected
    assert len(window.items) == 2
    last = await store.schemas(expected[-5], 4)
    assert [(r.name, r.version) for r in last.items] == expected[-4:]
    assert not last.has_more
    assert await store.schemas(expected[-1], 4) == Window([], has_more=False)


async def schema_version_scenario(store: LakeStore) -> None:
    """The insert refuses a taken or later-held version and a skipped one, writing nothing."""
    base = schema_record()
    await insert_schemas(store, base, schema_record(version=2))
    for version in (1, 2):
        with pytest.raises(SchemaVersionExists) as taken:
            await insert_schemas(store, schema_record(version=version, title="changed"))
        assert taken.value.context == {"name": "org", "version": version, "latest_version": 2}
    for record, latest in [
        (schema_record(version=4), 2),
        (schema_record("heliophysics", 2, extends=base), 0),
    ]:
        with pytest.raises(SchemaInvalid) as gap:
            await insert_schemas(store, record)
        assert gap.value.context == {
            "problems": [
                {
                    "where": "/version",
                    "rule": "version_gap",
                    "message": f"expected version {latest + 1}, not {record.version}",
                }
            ],
            "total": 1,
        }
    assert await store.latest("org") == schema_record(version=2)
    assert await store.latest("heliophysics") is None


async def schema_race_scenario(store: LakeStore) -> None:
    """A racing insert of the same version waits for the first and then finds it taken."""
    base = schema_record()
    await insert_schemas(store, base)
    attempted, settled = asyncio.Event(), asyncio.Event()

    async def racer() -> None:
        attempted.set()
        with pytest.raises(SchemaVersionExists):
            await insert_schemas(store, schema_record(version=2, title="racer"))
        settled.set()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as tx:
            await tx.insert_schema(winner := schema_record(version=2))
            tasks.create_task(racer())
            await attempted.wait()
            await asyncio.sleep(0)
            assert not settled.is_set()
        await settled.wait()
    assert await store.latest("org") == winner


async def schema_constraint_scenario(store: LakeStore, refused: ConstraintRefusal) -> None:
    """One level of extension, org as the only base, strict names and digests are enforced."""
    base = schema_record()
    extension = schema_record("heliophysics", extends=base)
    await insert_schemas(store, base, extension)
    for record, constraint in [
        (schema_record("nested", extends=extension), "metadata_schemas_one_level"),
        (schema_record("Ext", extends=base), "metadata_schemas_name_check"),
        (schema_record("geology", extends=base, sha256="0" * 63), "metadata_schemas_sha256_check"),
        (schema_record(version=2, extends=base), "metadata_schemas_org_is_the_base"),
        (schema_record("geology"), "metadata_schemas_org_is_the_base"),
        (
            schema_record("geology", extends_id=UUID(int=7)),
            "metadata_schemas_extends_id_fkey",
        ),
    ]:
        with refused(constraint):
            await insert_schemas(store, record)
        assert await store.by_id(record.id) is None
    assert [(r.name, r.version) for r in (await store.schemas(None, 10)).items] == [
        ("heliophysics", 1),
        ("org", 1),
    ]
