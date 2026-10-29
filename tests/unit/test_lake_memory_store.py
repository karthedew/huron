"""Atomic buffered state and transaction-scoped locking for the lake fake."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from huron.core.foundation.retry import IdempotencyClaim, Replay, request_sha256
from huron.core.lake import AUDIT_VOCABULARY, AuditEntry, CatalogCreated, KeyWithdrawn
from huron.core.lake.ports import (
    LakeStore,
    LakeTransaction,
    MetadataSchemaStore,
    MetadataSchemaWriter,
)
from huron.core.metastore.lake import InMemoryLakeStore
from huron.core.metastore.lake.idempotency import ClaimRow
from huron.core.metastore.lake.memory import (
    InMemoryLakeTransaction,
    LdapGroupRow,
    RoleMappingRow,
    SigningKeyRow,
)
from huron.core.security.broker import CatalogRef, Role, RoleMappingReader, SigningKeyReader
from tests.lake_store_contract import (
    CommittedAudit,
    LakeSeed,
    MemoryCommittedAudit,
    MemorySeed,
    audit_commit_order_scenario,
    audit_commit_scenario,
    audit_constraint_scenario,
    audit_rollback_scenario,
    catalog_created,
    claim_expiry_scenario,
    claim_replay_scenario,
    claim_rollback_scenario,
    invalid_role_scope_scenario,
    memory_refusal,
    role_mapping_scenario,
    schema_constraint_scenario,
    schema_page_scenario,
    schema_race_scenario,
    schema_read_scenario,
    schema_record,
    schema_version_scenario,
    signing_key_scenario,
    store_root_scenario,
    transaction_error_scenario,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tests.unit.support import FakeClock

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
CLAIM = IdempotencyClaim("scientist", "create-helio", request_sha256("catalog", "helio"))
CATALOG_RECEIPT = Replay("catalog", UUID(int=1))


@pytest.mark.parametrize("scenario", [store_root_scenario, transaction_error_scenario])
async def test_public_store_scenarios(scenario: Callable[[LakeStore], Awaitable[None]]) -> None:
    """The fake satisfies the shared store-root scenarios."""
    await scenario(InMemoryLakeStore())


@pytest.mark.parametrize("seed", [False, True])
def test_seed_is_exact_and_store_state_is_independent(seed: bool) -> None:
    """The optional seed holds the ladder rows and audit pairs, and no state is shared."""
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
    assert store.tables.audit_actions == (set(AUDIT_VOCABULARY) if seed else set())
    store.tables.roles.clear()
    store.tables.audit_actions.clear()
    fresh = InMemoryLakeStore()
    assert len(fresh.tables.roles) == 4
    assert fresh.tables.audit_actions == set(AUDIT_VOCABULARY)
    assert not store.tables.ldap_groups
    assert not store.tables.group_role_map
    assert not store.tables.signing_keys
    assert not store.tables.audit_log
    assert not store.tables.idempotency_records
    assert not store.tables.metadata_schemas
    assert not store.tables.metadata_schema_refs


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
    base = schema_record()
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
            assert not buffer.metadata_schemas.taken("org", 1)
            buffer.metadata_schemas.insert(base)
            assert buffer.metadata_schemas.get(base.id) == base
            assert buffer.metadata_schemas.taken("org", 1)
            assert buffer.metadata_schemas.latest_version("org") == 1
            assert buffer.metadata_schemas.latest_version("heliophysics") == 0
            assert buffer.ldap_groups.get(new.name) == new
            assert buffer.ldap_groups.get(old.name) is None
            assert buffer.ldap_groups.get("temporary") is None
            assert buffer.group_role_map.get((new.name, catalog)) == mapping
            assert buffer.signing_keys.get(key.kid) == key
            assert store.tables.ldap_groups == {old.name: old}
            assert store.tables.group_role_map == {}
            assert store.tables.signing_keys == {}
            assert store.tables.metadata_schemas == {}
            if abort:
                raise ValueError("discard")
    except ValueError:
        assert abort
    assert store.tables.ldap_groups == ({old.name: old} if abort else {new.name: new})
    assert store.tables.group_role_map == ({} if abort else {(new.name, catalog): mapping})
    assert store.tables.signing_keys == ({} if abort else {key.kid: key})
    assert store.tables.metadata_schemas == ({} if abort else {base.id: base})
    assert store.tables.metadata_schema_refs == ({} if abort else {("org", 1): base.id})
    assert store.tables.roles[role.code] == role


async def test_closed_transaction_rejects_saved_buffers_and_lock_acquisition() -> None:
    """Even a saved table buffer cannot be used after its transaction exits."""
    store = InMemoryLakeStore()
    async with store.transaction() as transaction:
        rows = transaction.buffer.ldap_groups
        schemas = transaction.buffer.metadata_schemas
    actions = [
        lambda: rows.get("group"),
        lambda: rows.put("group", LdapGroupRow("group", 101, NOW)),
        lambda: rows.delete("group"),
        lambda: schemas.get(UUID(int=1)),
        lambda: schemas.taken("org", 1),
        lambda: schemas.latest_version("org"),
        lambda: schemas.insert(schema_record()),
        transaction.buffer.apply,
    ]
    for action in actions:
        with pytest.raises(RuntimeError, match="closed"):
            action()
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.lock("key")
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.lock_catalog("catalog", shared=True)
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.append_audit([catalog_created("late")])
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.claim(CLAIM)
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.remember(CLAIM, CATALOG_RECEIPT)
    with pytest.raises(RuntimeError, match="closed"):
        await transaction.insert_schema(schema_record())
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
        (MetadataSchemaStore, InMemoryLakeStore),
        (RoleMappingReader, InMemoryLakeStore),
        (SigningKeyReader, InMemoryLakeStore),
        (LakeTransaction, InMemoryLakeTransaction),
        (MetadataSchemaWriter, InMemoryLakeTransaction),
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


@pytest.mark.parametrize(
    ("composite", "methods"),
    [
        (
            InMemoryLakeStore,
            {"by_ref", "by_id", "latest", "schemas", "roles_for_groups", "unexpired"},
        ),
        (InMemoryLakeTransaction, {"append_audit", "claim", "remember", "insert_schema"}),
    ],
)
def test_composed_halves_have_no_colliding_public_names(
    composite: type[object], methods: set[str]
) -> None:
    """A new half cannot silently shadow another half's public method."""
    names: set[str] = set()
    for half in composite.__bases__:
        public = {
            name
            for name, member in vars(half).items()
            if callable(member) and not name.startswith("_")
        }
        assert not names & public
        names.update(public)
    assert names == methods


@pytest.mark.parametrize(
    "scenario", [audit_commit_scenario, audit_rollback_scenario, audit_commit_order_scenario]
)
async def test_audit_scenarios(
    scenario: Callable[[LakeStore, CommittedAudit], Awaitable[None]],
) -> None:
    """The audit half satisfies the shared commit, rollback and ordering contracts."""
    store = InMemoryLakeStore()
    await scenario(store, MemoryCommittedAudit(store))


async def test_audit_constraint_scenario() -> None:
    """The fake refuses unseeded pairs and catalog-less collection entries by constraint name."""
    store = InMemoryLakeStore()
    await audit_constraint_scenario(store, MemoryCommittedAudit(store), memory_refusal)


@pytest.mark.parametrize("scenario", [claim_replay_scenario, claim_rollback_scenario])
async def test_claim_scenarios(scenario: Callable[[LakeStore], Awaitable[None]]) -> None:
    """The claims half satisfies the shared replay and rollback contracts."""
    await scenario(InMemoryLakeStore())


@pytest.mark.parametrize(
    "replay",
    [
        Replay("catalog", UUID(int=1)),
        Replay("metadata_schema", UUID(int=2)),
        Replay("signing_key", UUID(int=3)),
    ],
)
async def test_claim_expiry_scenario(clock: FakeClock, replay: Replay) -> None:
    """Every lake receipt kind expires with its claim under the injected clock."""
    await claim_expiry_scenario(InMemoryLakeStore(clock=clock), clock, replay)


async def test_an_unseeded_store_refuses_every_audit_pair() -> None:
    """Without the vocabulary rows, even a defined event breaks the vocabulary reference."""
    store = InMemoryLakeStore(seed=False)
    with memory_refusal("audit_log_vocabulary"):
        async with store.transaction() as tx:
            await tx.append_audit([catalog_created("helio")])
    assert store.tables.audit_log == {}


def _overlong_reason() -> AuditEntry:
    """Build an entry whose reason only a bypassed value check could carry."""
    bypassed = catalog_created("helio")
    object.__setattr__(bypassed, "reason", "x" * 1001)
    return bypassed


@pytest.mark.parametrize(
    ("constraint", "invalid"),
    [
        (
            "audit_log_actor_check",
            lambda: replace(catalog_created("helio"), actor="system:" + "a" * 154),
        ),
        (
            "audit_log_object_id_check",
            lambda: AuditEntry(NOW, "scientist", KeyWithdrawn(kid="", active_from=NOW)),
        ),
        (
            "audit_log_object_id_check",
            lambda: AuditEntry(NOW, "scientist", KeyWithdrawn(kid="k" * 256, active_from=NOW)),
        ),
        ("audit_log_reason_check", _overlong_reason),
    ],
)
async def test_audit_column_checks_refuse_the_whole_batch(
    constraint: str, invalid: Callable[[], AuditEntry]
) -> None:
    """A batch with one row breaking a column CHECK stages none of its entries."""
    store = InMemoryLakeStore()
    async with store.transaction() as tx:
        with memory_refusal(constraint):
            await tx.append_audit([catalog_created("valid"), invalid()])
    assert store.tables.audit_log == {}


async def test_an_unencodable_entry_stages_none_of_its_batch() -> None:
    """Detail encoding happens on append, so a failure leaves the batch unstaged."""
    store = InMemoryLakeStore()
    malformed = AuditEntry(
        NOW, "scientist", CatalogCreated(catalog=UUID(int=1), name=1.5, config_version=1)
    )
    async with store.transaction() as tx:
        with pytest.raises(TypeError):
            await tx.append_audit([catalog_created("valid"), malformed])
    assert store.tables.audit_log == {}
    assert store.tables.next_audit_id == 1


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"principal": ""}, "idempotency_records_principal_check"),
        ({"principal": "p" * 161}, "idempotency_records_principal_check"),
        ({"key": ""}, "idempotency_records_key_check"),
        ({"key": "k" * 256}, "idempotency_records_key_check"),
        ({"request_sha256": "A" * 64}, "idempotency_records_request_sha256_check"),
        ({"request_sha256": "a" * 63}, "idempotency_records_request_sha256_check"),
    ],
)
async def test_claim_checks_refuse_malformed_claims(
    change: dict[str, Any], constraint: str
) -> None:
    """A claim that breaks a column CHECK is refused and leaves no row."""
    store = InMemoryLakeStore()
    with memory_refusal(constraint):
        async with store.transaction() as tx:
            await tx.claim(replace(CLAIM, **change))
    assert store.tables.idempotency_records == {}


@pytest.mark.parametrize("kind", ["organization", "project", "dataset"])
async def test_lake_receipts_refuse_hierarchy_kinds(kind: str) -> None:
    """Only the five lake receipt kinds fit the lake's retry table."""
    store = InMemoryLakeStore()
    async with store.transaction() as tx:
        await tx.claim(CLAIM)
        with memory_refusal("idempotency_records_replay_kind_check"):
            await tx.remember(CLAIM, Replay(kind, UUID(int=1)))
        await tx.remember(CLAIM, CATALOG_RECEIPT)
    assert store.tables.idempotency_records[("scientist", "create-helio")].replay == CATALOG_RECEIPT


async def test_claim_rows_must_outlive_their_creation() -> None:
    """A row whose expiry does not follow its creation breaks the lifetime CHECK."""
    store = InMemoryLakeStore()
    async with store.transaction() as tx:
        with memory_refusal("idempotency_records_lifetime"):
            tx.buffer.idempotency_records.put(
                ("scientist", "create-helio"), ClaimRow(CLAIM, None, NOW, NOW)
            )


async def test_remember_needs_the_exact_claim_this_transaction_holds(clock: FakeClock) -> None:
    """No receipt without a held claim, for another fingerprint, or for another's claim."""
    store = InMemoryLakeStore(clock=clock)
    async with store.transaction() as tx:
        with pytest.raises(RuntimeError, match="holds"):
            await tx.remember(CLAIM, CATALOG_RECEIPT)
        await tx.claim(CLAIM)
        other = replace(CLAIM, request_sha256=request_sha256("catalog", "geo"))
        with pytest.raises(RuntimeError, match="holds"):
            await tx.remember(other, CATALOG_RECEIPT)
    async with store.transaction() as tx:
        with pytest.raises(RuntimeError, match="holds"):
            await tx.remember(CLAIM, CATALOG_RECEIPT)


async def test_a_concurrent_claim_waits_and_replays_the_committed_receipt(
    clock: FakeClock,
) -> None:
    """A competing transaction cannot take a held key until its holder commits."""
    store = InMemoryLakeStore(clock=clock)
    attempted, acquired = asyncio.Event(), asyncio.Event()

    async def contender() -> None:
        async with store.transaction() as tx:
            attempted.set()
            assert await tx.claim(CLAIM) == CATALOG_RECEIPT
            acquired.set()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as tx:
            await tx.claim(CLAIM)
            tasks.create_task(contender())
            await attempted.wait()
            await asyncio.sleep(0)
            assert not acquired.is_set()
            await tx.remember(CLAIM, CATALOG_RECEIPT)
        await acquired.wait()


async def test_claims_default_to_the_system_clock() -> None:
    """Without an injected clock a claim's lifetime starts at the current UTC time."""
    store = InMemoryLakeStore()
    before = datetime.now(UTC)
    async with store.transaction() as tx:
        await tx.claim(CLAIM)
    row = store.tables.idempotency_records[("scientist", "create-helio")]
    assert before <= row.created_at <= datetime.now(UTC)
    assert row.expires_at - row.created_at == timedelta(hours=24)


@pytest.mark.parametrize(
    "scenario",
    [schema_read_scenario, schema_page_scenario, schema_version_scenario, schema_race_scenario],
)
async def test_schema_scenarios(scenario: Callable[[LakeStore], Awaitable[None]]) -> None:
    """The schema halves satisfy the shared read, paging, version and race contracts."""
    await scenario(InMemoryLakeStore())


async def test_schema_constraint_scenario() -> None:
    """The fake refuses schema rows by the name of the PostgreSQL constraint or trigger."""
    await schema_constraint_scenario(InMemoryLakeStore(), memory_refusal)


@pytest.mark.parametrize(
    ("duplicate", "constraint"),
    [
        (
            lambda base: schema_record("heliophysics", id=base.id, extends=base),
            "metadata_schemas_pkey",
        ),
        (lambda base: schema_record(title="again"), "metadata_schemas_name_version_key"),
    ],
)
async def test_schema_keys_back_up_the_version_decision(
    duplicate: Callable[[Any], Any], constraint: str
) -> None:
    """A row bypassing the insert's version decision still cannot reuse an id or a version."""
    store = InMemoryLakeStore()
    base = schema_record()
    async with store.transaction() as tx:
        await tx.insert_schema(base)
        with memory_refusal(constraint):
            tx.buffer.metadata_schemas.insert(duplicate(base))
    assert store.tables.metadata_schemas == {base.id: base}


async def test_a_transaction_may_lock_a_key_it_already_holds() -> None:
    """Locking a held key again neither waits nor lets a competing transaction in early."""
    store = InMemoryLakeStore()
    attempted, acquired = asyncio.Event(), asyncio.Event()

    async def contender() -> None:
        async with store.transaction() as transaction:
            attempted.set()
            await transaction.lock("same")
            acquired.set()

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        async with store.transaction() as transaction:
            await transaction.lock("same")
            await transaction.lock("same")
            tasks.create_task(contender())
            await attempted.wait()
            await asyncio.sleep(0)
            assert not acquired.is_set()
        await acquired.wait()
