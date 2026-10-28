"""Atomic buffered state and transaction-scoped locking for the lake fake."""

from __future__ import annotations

from dataclasses import replace

from huron.core.foundation.retry import IdempotencyClaim, Replay
from huron.core.lake.audit import AUDIT_VOCABULARY, CollectionCreated, KeyWithdrawn
from huron.core.metastore.lake.memory import IntegrityViolation

import asyncio
import inspect
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from huron.core.lake.ports import LakeStore, LakeTransaction
from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.metastore.lake.memory import (
    InMemoryLakeTransaction,
    LdapGroupRow,
    RoleMappingRow,
    SigningKeyRow,
)
from huron.core.security.broker import CatalogRef, Role, RoleMappingReader, SigningKeyReader
from tests.lake_store_contract import (
    LakeSeed,
    MemoryAuditRows,
    audit_entry,
    audit_transaction_scenario,
    audit_commit_order_scenario,
    claims_scenario,
    MemorySeed,
    role_mapping_scenario,
    invalid_role_scope_scenario,
    signing_key_scenario,
    store_root_scenario,
    transaction_error_scenario,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


@pytest.mark.parametrize("scenario", [store_root_scenario, transaction_error_scenario])
async def test_public_store_scenarios(scenario: Callable[[LakeStore], Awaitable[None]]) -> None:
    """The fake satisfies the shared store-root scenarios."""
    await scenario(InMemoryLakeStore())


@pytest.mark.parametrize("seed", [False, True])
def test_role_seed_is_exact_and_store_state_is_independent(seed: bool) -> None:
    """The optional seed has exactly the ladder rows and no mutable state is shared."""
    store = InMemoryLakeStore(seed=seed)
    expected = (
        {
            (role.code, role.title, int(role), "catalog" if role.catalog_scoped else "organization")
            for role in Role
        }
        if seed
        else set()
    )
    assert {(r.code, r.title, r.rank, r.scope) for r in store.tables.roles.values()} == expected
    assert set(store.tables.roles) == {row[0] for row in expected}
    store.tables.roles.clear()
    assert len(InMemoryLakeStore().tables.roles) == 4
    assert not store.tables.ldap_groups
    assert not store.tables.group_role_map
    assert not store.tables.signing_keys


@pytest.mark.parametrize("abort", [False, True])
async def test_buffer_reads_own_changes_and_commits_or_discards_all_tables(abort: bool) -> None:
    """Pending puts and tombstones are private, then every table changes together or not at all."""
    store = InMemoryLakeStore()
    old = LdapGroupRow("old", 101, NOW)
    new = LdapGroupRow("new", 102, NOW)
    store.tables.ldap_groups[old.name] = old
    role = store.tables.roles["catalog_reader"]
    catalog = UUID(int=1)
    mapping = RoleMappingRow(
        new.name, CatalogRef(catalog, "heliophysics"), role.code, role.scope, NOW, "scientist"
    )
    members = {"kty": "EC"}
    key = SigningKeyRow("kid", "ES256", members, "key.pem", NOW, None, NOW, "scientist")
    members["kty"] = "changed"
    assert key.public_jwk == {"kty": "EC"}
    with pytest.raises(TypeError):
        key.public_jwk["kty"] = "changed"
    try:
        async with store.transaction() as transaction:
            buffer = transaction.buffer
            assert buffer.ldap_groups.get(old.name) == old
            assert buffer.ldap_groups.get("absent") is None
            buffer.ldap_groups.put(new.name, new)
            buffer.ldap_groups.delete(old.name)
            buffer.ldap_groups.delete("absent")
            buffer.ldap_groups.put("temporary", old)
            buffer.ldap_groups.delete("temporary")
            buffer.ldap_groups.delete(new.name)
            buffer.ldap_groups.put(new.name, new)
            buffer.roles.delete(role.code)
            buffer.roles.put(role.code, role)
            buffer.group_role_map.put((new.name, catalog), mapping)
            buffer.signing_keys.put(key.kid, key)
            assert buffer.ldap_groups.get(new.name) == new
            assert buffer.ldap_groups.get(old.name) is None
            assert buffer.ldap_groups.get("temporary") is None
            assert buffer.group_role_map.get((new.name, catalog)) == mapping
            assert buffer.signing_keys.get(key.kid) == key
            assert store.tables.ldap_groups == {old.name: old}
            assert store.tables.group_role_map == {}
            assert store.tables.signing_keys == {}
            if abort:
                raise ValueError("discard")
    except ValueError:
        assert abort
    assert store.tables.ldap_groups == ({old.name: old} if abort else {new.name: new})
    assert store.tables.group_role_map == ({} if abort else {(new.name, catalog): mapping})
    assert store.tables.signing_keys == ({} if abort else {key.kid: key})
    assert store.tables.roles[role.code] == role


async def test_closed_transaction_rejects_saved_buffers_and_lock_acquisition() -> None:
    """Even a saved table buffer cannot be used after its transaction exits."""
    store = InMemoryLakeStore()
    async with store.transaction() as transaction:
        rows = transaction.buffer.ldap_groups
    actions = [
        lambda: rows.get("group"),
        lambda: rows.put("group", LdapGroupRow("group", 101, NOW)),
        lambda: rows.delete("group"),
        transaction.buffer.apply,
    ]
    for action in actions:
        with pytest.raises(RuntimeError, match="closed"):
            action()
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.lock("key")
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.lock_catalog("catalog", shared=True)
    transaction.close()


async def test_nesting_refusal_preserves_outer_transaction_and_allows_other_stores() -> None:
    """A rejected nested open does not close its outer transaction or affect another store."""
    store = InMemoryLakeStore()
    row = LdapGroupRow("group", 101, NOW)
    async with store.transaction() as transaction:
        transaction.buffer.ldap_groups.put(row.name, row)
        with pytest.raises(RuntimeError, match="nested"):
            async with store.transaction():
                pytest.fail("nested transaction entered")
        async with InMemoryLakeStore().transaction():
            pass
        assert transaction.buffer.ldap_groups.get(row.name) == row
    assert store.tables.ldap_groups[row.name] == row
    async with store.transaction():
        pass


async def _lock(transaction: InMemoryLakeTransaction, mode: str, key: str = "same") -> None:
    """Acquire one of the fake's resource-lock modes."""
    if mode == "exclusive":
        await transaction.lock(key)
    else:
        await transaction.lock_catalog(key, shared=mode == "reader")


@pytest.mark.parametrize(
    ("first", "second", "coexist"),
    [
        ("exclusive", "exclusive", False),
        ("reader", "reader", True),
        ("reader", "writer", False),
        ("writer", "reader", False),
        ("writer", "writer", False),
    ],
)
async def test_lock_modes_serialize_or_coexist(first: str, second: str, coexist: bool) -> None:
    """Independent tasks obey exclusive and shared catalog lock compatibility."""
    store = InMemoryLakeStore()
    attempted, acquired, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def contender() -> None:
        async with store.transaction() as transaction:
            attempted.set()
            await _lock(transaction, second)
            acquired.set()
            await release.wait()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as transaction:
            await _lock(transaction, first)
            tasks.create_task(contender())
            await attempted.wait()
            if coexist:
                await acquired.wait()
            else:
                assert not acquired.is_set()
        await acquired.wait()
        release.set()


@pytest.mark.parametrize("mode", ["exclusive", "reader", "writer"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_releases_every_lock_and_discards_pending_rows(
    mode: str, cancel: bool
) -> None:
    """Exceptions and cancellation discard rows and release all acquired resource locks."""
    store = InMemoryLakeStore()
    holding, fail = asyncio.Event(), asyncio.Event()
    row = LdapGroupRow("group", 101, NOW)

    async def holder() -> None:
        async with store.transaction() as transaction:
            await _lock(transaction, mode)
            await _lock(transaction, mode, "other")
            transaction.buffer.ldap_groups.put(row.name, row)
            holding.set()
            await fail.wait()
            raise ValueError("abort")

    async with asyncio.timeout(5):
        task = asyncio.create_task(holder())
        await holding.wait()
        if cancel:
            task.cancel()
        else:
            fail.set()
        with pytest.raises(asyncio.CancelledError if cancel else ValueError):
            await task
        assert not store.tables.ldap_groups
        async with store.transaction() as transaction:
            for key in ("same", "other"):
                await _lock(transaction, "exclusive" if mode == "exclusive" else "writer", key)


@pytest.mark.parametrize("mode", ["exclusive", "reader", "writer"])
async def test_cancelled_waiter_does_not_leak_or_release_another_holders_lock(mode: str) -> None:
    """Cancelling a waiter leaves the holder's lock intact and later acquisition succeeds."""
    store = InMemoryLakeStore()
    attempted, acquired = asyncio.Event(), asyncio.Event()

    async def waiter() -> None:
        async with store.transaction() as transaction:
            attempted.set()
            await _lock(transaction, mode)
            acquired.set()

    async with asyncio.timeout(5):
        async with store.transaction() as transaction:
            await _lock(transaction, "exclusive" if mode == "exclusive" else "writer")
            task = asyncio.create_task(waiter())
            await attempted.wait()
            assert not acquired.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            attempted.clear()
            task = asyncio.create_task(waiter())
            await attempted.wait()
            assert not acquired.is_set()
        await task
        assert acquired.is_set()


def test_stores_conform_to_their_ports_structurally_not_by_inheritance() -> None:
    """Both composites expose every protocol member with the same parameter names and kinds."""
    for port, adapter in [
        (LakeStore, InMemoryLakeStore),
        (RoleMappingReader, InMemoryLakeStore),
        (SigningKeyReader, InMemoryLakeStore),
        (LakeTransaction, InMemoryLakeTransaction),
    ]:
        assert port not in adapter.__mro__
        for name, member in inspect.getmembers(port, inspect.isfunction):
            if name.startswith("_"):
                continue
            actual = getattr(adapter, name)
            expected_parameters = inspect.signature(member).parameters.values()
            actual_parameters = inspect.signature(actual).parameters.values()
            assert [(p.name, p.kind) for p in actual_parameters] == [
                (p.name, p.kind) for p in expected_parameters
            ]


async def test_independent_keys_and_concurrent_commits_preserve_both_rows() -> None:
    """Unrelated locks coexist and committing a buffer preserves another transaction's rows."""
    store = InMemoryLakeStore()
    staged, commit = asyncio.Event(), asyncio.Event()
    first = LdapGroupRow("first", 101, NOW)
    second = LdapGroupRow("second", 102, NOW)

    async def other() -> None:
        async with store.transaction() as transaction:
            await transaction.lock("second")
            await transaction.lock_catalog("second", shared=False)
            transaction.buffer.ldap_groups.put(second.name, second)
            staged.set()
            await commit.wait()
            assert transaction.buffer.ldap_groups.get(first.name) == first

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as transaction:
            await transaction.lock("first")
            await transaction.lock_catalog("first", shared=False)
            transaction.buffer.ldap_groups.put(first.name, first)
            tasks.create_task(other())
            await staged.wait()
            assert store.tables.ldap_groups == {}
            assert transaction.buffer.ldap_groups.get(second.name) is None
        assert store.tables.ldap_groups == {first.name: first}
        commit.set()
    assert store.tables.ldap_groups == {first.name: first, second.name: second}


@pytest.mark.parametrize(
    "scenario", [role_mapping_scenario, invalid_role_scope_scenario, signing_key_scenario]
)
async def test_seeded_store_scenarios(
    scenario: Callable[[LakeStore, LakeSeed], Awaitable[None]],
) -> None:
    """Read halves satisfy the shared role and signing-key contracts."""
    store = InMemoryLakeStore()
    await scenario(store, MemorySeed(store))


@pytest.mark.parametrize(
    ("role", "scope", "catalog"),
    [
        ("catalog_reader", "catalog", None),
        ("catalog_contributor", "catalog", None),
        ("catalog_owner", "catalog", None),
        ("administrator", "organization", CatalogRef(UUID(int=1), "helio")),
        ("catalog_reader", "organization", CatalogRef(UUID(int=1), "helio")),
        ("administrator", "catalog", None),
        ("reader", "organization", None),
    ],
)
async def test_reader_refuses_corrupt_role_scopes(
    role: str, scope: str, catalog: CatalogRef | None
) -> None:
    """Malformed persisted rows raise instead of becoming unrestricted grants."""
    store = InMemoryLakeStore()
    row = RoleMappingRow("broken", catalog, role, scope, NOW, "seed")
    store.tables.group_role_map[("broken", catalog.id if catalog else None)] = row
    with pytest.raises(ValueError):
        await store.roles_for_groups(frozenset({"broken"}))
    assert await store.roles_for_groups(frozenset()) == ()


async def test_memory_seed_requires_registered_group() -> None:
    """Missing directory groups cannot acquire mappings through the seeding seam."""
    store = InMemoryLakeStore()
    with pytest.raises(ValueError, match="registered"):
        await MemorySeed(store).role_mapping("absent", None, Role.ADMINISTRATOR)
    assert await store.roles_for_groups(frozenset({"absent"})) == ()


def test_composed_halves_have_no_colliding_public_names() -> None:
    """A new half cannot silently shadow another half's public method."""
    names: set[str] = set()
    for half in InMemoryLakeStore.__bases__:
        public = {name for name in vars(half) if not name.startswith("_")}
        assert not names & public
        names.update(public)
    assert {"roles_for_groups", "unexpired"} <= names


@pytest.mark.parametrize("scenario", [audit_transaction_scenario, audit_commit_order_scenario])
async def test_audit_store_scenarios(scenario):
    """The fake preserves shared audit visibility and order contracts."""
    store = InMemoryLakeStore()
    await scenario(store, MemoryAuditRows(store))


@pytest.mark.parametrize("kind", ["catalog", "metadata_schema", "signing_key"])
async def test_claim_store_scenarios(clock, kind):
    """Every currently consumed lake receipt uses the same strict lifetime."""
    store = InMemoryLakeStore(clock=clock)
    await claims_scenario(store, clock, kind)


@pytest.mark.parametrize("seed", [False, True])
def test_audit_seed_matches_the_domain_vocabulary(seed):
    """Only seeded stores install the fourteen accepted pairs."""
    assert InMemoryLakeStore(seed=seed).tables.audit_actions == (
        set(AUDIT_VOCABULARY) if seed else set()
    )


@pytest.mark.parametrize(
    "constraint,changes",
    [
        ("audit_log_actor_check", {"actor": "system:" + "a" * 154}),
        ("audit_log_object_id_check", {"event": KeyWithdrawn(kid="", active_from=NOW)}),
        ("audit_log_object_id_check", {"event": KeyWithdrawn(kid="k" * 256, active_from=NOW)}),
        (
            "audit_log_collection_has_catalog",
            {
                "event": CollectionCreated(
                    collection=UUID(int=1), catalog=None, version=1, config_version=1
                )
            },
        ),
    ],
)
async def test_audit_table_constraints(constraint, changes):
    """The fake enforces SQL backstops in addition to domain value validation."""
    store = InMemoryLakeStore()
    entry = replace(audit_entry(), **changes)
    with pytest.raises(IntegrityViolation) as caught:
        async with store.transaction() as tx:
            await tx.append_audit([audit_entry(), entry])
    assert caught.value.constraint == constraint
    assert store.tables.audit_log == {}


async def test_unseeded_audit_pair_is_refused():
    """An absent vocabulary row refuses the entire batch with its FK name."""
    store = InMemoryLakeStore(seed=False)
    with pytest.raises(IntegrityViolation, match="audit_log_vocabulary"):
        async with store.transaction() as tx:
            await tx.append_audit([audit_entry()])


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("principal", "", "principal"),
        ("principal", "x" * 161, "principal"),
        ("key", "", "key"),
        ("key", "x" * 256, "key"),
        ("request_sha256", "A" * 64, "request_sha256"),
        ("request_sha256", "a" * 63, "request_sha256"),
    ],
)
async def test_claim_table_constraints(field, value, constraint):
    """Malformed claim identities fail with the corresponding persisted CHECK name."""
    store = InMemoryLakeStore()
    with pytest.raises(IntegrityViolation, match=f"idempotency_records_{constraint}_check"):
        async with store.transaction() as tx:
            await tx.claim(
                replace(IdempotencyClaim("scientist", "key", "a" * 64), **{field: value})
            )
    assert store.tables.idempotency_records == {}


async def test_receipt_requires_held_claim_and_valid_lake_kind():
    """Remember cannot invent a claim, change its fingerprint or store a legacy receipt."""
    store = InMemoryLakeStore()
    claim = IdempotencyClaim("scientist", "key", "a" * 64)
    replay = Replay("catalog", UUID(int=1))
    async with store.transaction() as tx:
        with pytest.raises(RuntimeError, match="matching claim"):
            await tx.remember(claim, replay)
        await tx.claim(claim)
        with pytest.raises(RuntimeError, match="matching claim"):
            await tx.remember(replace(claim, request_sha256="b" * 64), replay)
        with pytest.raises(IntegrityViolation, match="replay_kind_check"):
            await tx.remember(claim, replace(replay, kind="organization"))
        with pytest.raises(IntegrityViolation, match="records_receipt"):
            await tx.remember(claim, replace(replay, resource_id=None))
        await tx.remember(claim, replay)
    with pytest.raises(RuntimeError, match="closed"):
        await tx.claim(claim)
    with pytest.raises(RuntimeError, match="closed"):
        await tx.remember(claim, replay)
    with pytest.raises(RuntimeError, match="closed"):
        await tx.append_audit([audit_entry()])


async def test_audit_constraint_checks_reject_corrupted_reason():
    """The persistence backstop rejects a malformed reason even if value checks were bypassed."""
    entry = audit_entry()
    object.__setattr__(entry, "reason", "x" * 1001)
    store = InMemoryLakeStore()
    with pytest.raises(IntegrityViolation, match="audit_log_reason_check"):
        async with store.transaction() as tx:
            await tx.append_audit([entry])


async def test_failed_audit_encoding_discards_all_mutations():
    """Serialization failure cannot leave another table or an earlier audit row committed."""
    store = InMemoryLakeStore()
    entry = audit_entry()
    object.__setattr__(entry.event, "name", object())
    with pytest.raises(TypeError):
        async with store.transaction() as tx:
            tx.buffer.ldap_groups.put("group", LdapGroupRow("group", 1, NOW))
            await tx.append_audit([audit_entry(), entry])
    assert store.tables.ldap_groups == {}
    assert store.tables.audit_log == {}


async def test_concurrent_claim_waits_and_replays_committed_receipt(clock):
    """A competing transaction cannot acquire the same request before its holder commits."""
    store = InMemoryLakeStore(clock=clock)
    claim = IdempotencyClaim("scientist", "key", "a" * 64)
    replay = Replay("catalog", UUID(int=1))
    attempted, acquired = asyncio.Event(), asyncio.Event()

    async def contender():
        async with store.transaction() as tx:
            attempted.set()
            assert await tx.claim(claim) == replay
            acquired.set()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as tx:
            await tx.claim(claim)
            await tx.remember(claim, replay)
            tasks.create_task(contender())
            await attempted.wait()
            assert not acquired.is_set()
        await acquired.wait()
