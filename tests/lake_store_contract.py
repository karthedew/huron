"""Shared public-store scenarios for lake persistence adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

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
