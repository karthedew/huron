"""Shared public-store scenarios for lake persistence adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from huron.core.foundation.errors import IdempotencyKeyReused
from huron.core.foundation.retry import IdempotencyClaim, Replay
from huron.core.lake.audit import AuditEntry, AuditRecord, CatalogCreated
from tests.unit.support import FakeClock
from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.metastore.lake.memory import LdapGroupRow, RoleMappingRow, SigningKeyRow
from huron.core.security.broker import CatalogRef, Grant, Grants, Role, SigningKeyRecord
from tests.lake_tokens import TEST_EPOCH, TEST_RECORD


import pytest

if TYPE_CHECKING:
    from huron.core.lake.ports import LakeStore


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


class LakeAuditRows(Protocol):
    """Read committed audit rows before the domain history reader is available."""

    async def audit_rows(self) -> list[AuditRecord]:
        """Return the complete log in ascending ID order."""
        ...


class MemoryAuditRows:
    """Inspect committed fake audit rows for shared persistence scenarios."""

    def __init__(self, store: InMemoryLakeStore) -> None:
        self._store = store

    async def audit_rows(self) -> list[AuditRecord]:
        """Return rows in their assigned order."""
        return sorted(self._store.tables.audit_log.values(), key=lambda row: row.id)


def audit_entry(name: str = "helio") -> AuditEntry:
    """Build a catalog creation fact for persistence scenarios."""
    return AuditEntry(
        TEST_EPOCH, "scientist", CatalogCreated(catalog=UUID(int=1), name=name, config_version=1)
    )


async def audit_transaction_scenario(store: LakeStore, rows: LakeAuditRows) -> None:
    """Audit batches appear on commit, retain order and disappear on rollback."""
    first, second, third = (audit_entry(name) for name in ("first", "second", "third"))
    async with store.transaction() as tx:
        await tx.append_audit([first, second])
        await tx.append_audit([third])
        assert await rows.audit_rows() == []
    committed = await rows.audit_rows()
    assert [r.detail["name"] for r in committed] == ["first", "second", "third"]
    assert [r.id for r in committed] == sorted({r.id for r in committed})
    for entry, row in zip((first, second, third), committed, strict=True):
        assert (
            row.at,
            row.actor,
            row.action,
            row.object_type,
            row.object_id,
            row.catalog_id,
            row.detail,
            row.reason,
        ) == (
            entry.at,
            entry.actor,
            entry.event.ACTION,
            entry.event.OBJECT,
            entry.object_id,
            entry.catalog_id,
            entry.detail(),
            entry.reason,
        )
    with pytest.raises(ValueError, match="abort"):
        async with store.transaction() as tx:
            await tx.append_audit([first])
            raise ValueError("abort")
    assert await rows.audit_rows() == committed
    async with store.transaction() as tx:
        with pytest.raises(ValueError):
            await tx.append_audit([])


async def audit_commit_order_scenario(store: LakeStore, rows: LakeAuditRows) -> None:
    """IDs follow commit order even when transactions stage in the opposite order."""
    import asyncio

    staged, release = asyncio.Event(), asyncio.Event()

    async def later_commit() -> None:
        async with store.transaction() as tx:
            await tx.append_audit([audit_entry("later")])
            staged.set()
            await release.wait()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        tasks.create_task(later_commit())
        await staged.wait()
        async with store.transaction() as tx:
            await tx.append_audit([audit_entry("earlier")])
        release.set()
    assert [r.detail["name"] for r in await rows.audit_rows()] == ["earlier", "later"]


async def claims_scenario(store: LakeStore, clock: FakeClock, kind: str) -> None:
    """Matching claims replay, mismatches fail, and every kind expires at exactly 24 hours."""
    claim = IdempotencyClaim("scientist", "request", "a" * 64)
    replay = Replay(kind, UUID(int=1))
    other = replace(claim, request_sha256="b" * 64)
    async with store.transaction() as tx:
        assert await tx.claim(claim) is None
        assert await tx.claim(claim) is None
        await tx.remember(claim, replay)
        assert await tx.claim(claim) == replay
    clock.advance(timedelta(hours=24) - timedelta(microseconds=1))
    async with store.transaction() as tx:
        assert await tx.claim(claim) == replay
        with pytest.raises(IdempotencyKeyReused):
            await tx.claim(other)
    clock.advance(timedelta(microseconds=1))
    async with store.transaction() as tx:
        assert await tx.claim(other) is None
        await tx.remember(other, replay)
    with pytest.raises(ValueError, match="abort"):
        async with store.transaction() as tx:
            await tx.claim(replace(claim, key="rolled-back"))
            await tx.append_audit([audit_entry()])
            raise ValueError("abort")
    async with store.transaction() as tx:
        assert await tx.claim(replace(other, key="rolled-back")) is None
        assert await tx.claim(replace(other, principal="other")) is None
