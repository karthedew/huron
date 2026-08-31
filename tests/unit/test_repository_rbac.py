"""Direct unit tests for the RBAC storage seam: InMemoryRbacStore, the
HierarchyRepository delegation, the API-key touch bookkeeping, and the
per-request binding cache in ``authorization.check``/``cached_bindings_for``.

PostgresRbacStore and PostgresApiKeyStore are exercised only by
``tests/contract/test_rbac_store.py`` against a real database - asyncpg rows
are not worth faking here, and the SQL is the part a fake can't verify.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.pkg.auth import ApiKeyRecord, MemoryApiKeyStore
from huron.pkg.auth import Principal as AuthPrincipal
from huron.pkg.catalog.errors import DomainError
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Binding, Decision, Effect, Principal, Scope, ScopeType, decide
from huron.pkg.rbac.roles import PrincipalKindNotAllowed, ScopeNotBindable
from huron.service.api.authorization import cached_bindings_for, check
from huron.service.api.repository import (
    HierarchyRepository,
    InMemoryRbacStore,
    ResourceNotFound,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    return HierarchyRepository(PosixRawStore(str(tmp_path / "raw")))


# -- InMemoryRbacStore --------------------------------------------------------


async def test_grant_role_compiles_the_same_binding_shape_compile_binding_produces() -> None:
    store = InMemoryRbacStore()
    project_id = uuid4()
    record = await store.grant_role(
        principal="user:bob",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        created_by="alice",
    )
    assert record.role_code == "developer"
    assert record.scope_id == project_id

    bindings = await store.bindings_for(frozenset({"user:bob"}))
    # One control-plane binding (layers=None) plus one binding per layer
    # grant (data.read with every layer, data.write restricted to raw+bronze).
    assert len(bindings) == 3
    control_plane = next(b for b in bindings if "dataset.create" in b.capabilities)
    assert control_plane.layers is None
    read = next(b for b in bindings if b.capabilities == frozenset({"data.read"}))
    assert read.layers is None
    write = next(b for b in bindings if b.capabilities == frozenset({"data.write"}))
    assert write.layers == frozenset({"raw", "bronze"})


async def test_grant_role_validates_before_any_binding_is_stored() -> None:
    """A role/kind mismatch never reaches storage - there is no partial write."""
    store = InMemoryRbacStore()
    with pytest.raises(PrincipalKindNotAllowed):
        await store.grant_role(
            principal="user:bob",
            role_code="pipeline",
            scope_type=ScopeType.PROJECT,
            scope_id=uuid4(),
            created_by="alice",
        )
    with pytest.raises(ScopeNotBindable):
        await store.grant_role(
            principal="user:bob",
            role_code="platform_owner",
            scope_type=ScopeType.ORGANIZATION,
            scope_id=uuid4(),
            created_by="alice",
        )
    assert await store.bindings_for(frozenset({"user:bob"})) == ()


async def test_grant_role_rejects_an_identical_duplicate() -> None:
    store = InMemoryRbacStore()
    scope_id = uuid4()
    await store.grant_role(
        principal="user:bob",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        created_by="alice",
    )
    with pytest.raises(DomainError):
        await store.grant_role(
            principal="user:bob",
            role_code="reader",
            scope_type=ScopeType.PROJECT,
            scope_id=scope_id,
            created_by="alice",
        )


async def test_expired_binding_is_denied_by_decide() -> None:
    store = InMemoryRbacStore()
    scope_id = uuid4()
    await store.grant_role(
        principal="user:bob",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        created_by="alice",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    bindings = await store.bindings_for(frozenset({"user:bob"}))
    actor = Principal(subject="bob")
    scope = Scope(ScopeType.PROJECT, scope_id, project_id=scope_id)
    assert decide(bindings, actor, "dataset.discover", scope) is Decision.DENY


async def test_revoke_role_removes_the_binding_and_its_compiled_capabilities() -> None:
    store = InMemoryRbacStore()
    scope_id = uuid4()
    record = await store.grant_role(
        principal="user:bob",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        created_by="alice",
    )
    assert await store.bindings_for(frozenset({"user:bob"})) != ()

    await store.revoke_role(record.id)

    assert await store.bindings_for(frozenset({"user:bob"})) == ()
    with pytest.raises(ResourceNotFound):
        await store.get_role_binding(record.id)
    with pytest.raises(ResourceNotFound):
        await store.revoke_role(record.id)


async def test_service_account_and_policy_listings_are_sorted_and_scoped() -> None:
    store = InMemoryRbacStore()
    organization_id = uuid4()
    other_organization_id = uuid4()
    await store.create_service_account(
        organization_id, name="zeta", subject="org/zeta", created_by="alice"
    )
    await store.create_service_account(
        organization_id, name="alpha", subject="org/alpha", created_by="alice"
    )
    await store.create_service_account(
        other_organization_id, name="beta", subject="other/beta", created_by="alice"
    )
    accounts = await store.list_service_accounts(organization_id)
    assert [item.name for item in accounts] == ["alpha", "zeta"]

    with pytest.raises(DomainError):
        await store.create_service_account(
            organization_id, name="alpha", subject="org/alpha-2", created_by="alice"
        )

    await store.create_policy(policy_type="retention", name="zzz", spec={}, created_by="alice")
    await store.create_policy(policy_type="retention", name="aaa", spec={}, created_by="alice")
    policies = await store.list_policies()
    assert [item.name for item in policies] == ["aaa", "zzz"]


async def test_attach_policy_rejects_unknown_policy_and_duplicate_attachment() -> None:
    store = InMemoryRbacStore()
    with pytest.raises(ResourceNotFound):
        await store.attach_policy(
            uuid4(), scope_type=ScopeType.ORGANIZATION, scope_id=uuid4(), attached_by="alice"
        )

    policy = await store.create_policy(
        policy_type="retention", name="raw-90d", spec={"days": 90}, created_by="alice"
    )
    scope_id = uuid4()
    await store.attach_policy(
        policy.id, scope_type=ScopeType.ORGANIZATION, scope_id=scope_id, attached_by="alice"
    )
    with pytest.raises(DomainError):
        await store.attach_policy(
            policy.id, scope_type=ScopeType.ORGANIZATION, scope_id=scope_id, attached_by="alice"
        )


async def test_bindings_at_returns_system_scope_bindings_sorted_by_principal_then_role() -> None:
    store = InMemoryRbacStore()
    await store.grant_role(
        principal="user:carol",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="alice",
    )
    await store.grant_role(
        principal="user:bob",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="alice",
    )
    project_id = uuid4()
    await store.grant_role(
        principal="user:aaron",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        created_by="alice",
    )

    system_bindings = await store.bindings_at(ScopeType.SYSTEM, None)
    assert [item.principal for item in system_bindings] == ["user:bob", "user:carol"]

    project_bindings = await store.bindings_at(ScopeType.PROJECT, project_id)
    assert [item.principal for item in project_bindings] == ["user:aaron"]

    assert await store.bindings_at(ScopeType.PROJECT, uuid4()) == []


# -- HierarchyRepository delegation -------------------------------------------


async def test_hierarchy_repository_checks_scope_existence_before_delegating(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        await repository.grant_role(
            principal="user:bob",
            role_code="reader",
            scope_type=ScopeType.PROJECT,
            scope_id=uuid4(),
            created_by="alice",
        )


async def test_hierarchy_repository_rejects_a_scope_id_at_system_scope(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(DomainError):
        await repository.grant_role(
            principal="user:bob",
            role_code="platform_owner",
            scope_type=ScopeType.SYSTEM,
            scope_id=uuid4(),
            created_by="alice",
        )


async def test_hierarchy_repository_rejects_a_missing_scope_id_below_system(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(DomainError):
        await repository.grant_role(
            principal="user:bob",
            role_code="reader",
            scope_type=ScopeType.PROJECT,
            scope_id=None,
            created_by="alice",
        )


async def test_hierarchy_repository_derives_service_account_subject_from_org_slug(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
    )
    account = await repository.create_service_account(
        organization.id, name="canonicalizer", created_by="alice"
    )
    assert account.subject == "astro/canonicalizer"
    fetched = await repository.get_service_account(account.principal_id)
    assert fetched == account


async def test_two_repositories_built_without_an_injected_store_do_not_share_bindings(
    tmp_path: Path,
) -> None:
    """Each ``HierarchyRepository()`` call must get its own ``InMemoryRbacStore``.

    A shared default instance (the classic Python mutable-default-argument
    trap, reached here through ``rbac_store: RbacStore | None = None``
    defaulting inside ``__init__`` rather than in the signature) would leak
    one repository's grants into every other repository built the same way.
    """
    first = HierarchyRepository(PosixRawStore(str(tmp_path / "raw-1")))
    second = HierarchyRepository(PosixRawStore(str(tmp_path / "raw-2")))

    await first.rbac_store.grant_role(
        principal="user:bob",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="alice",
    )

    assert await first.bindings_for(frozenset({"user:bob"})) != ()
    assert await second.bindings_for(frozenset({"user:bob"})) == ()


# -- API key touch bookkeeping -------------------------------------------------


async def test_memory_api_key_store_records_touch_calls() -> None:
    store = MemoryApiKeyStore()
    record = ApiKeyRecord(
        key_id="abc123",
        subject="alice",
        name="alice-laptop",
        secret_sha256="0" * 64,
        scopes=frozenset({"read"}),
        project_id=None,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await store.add(record)
    assert await store.get("abc123") == record
    assert store.touched == []

    await store.touch_last_used("abc123")
    assert store.touched == ["abc123"]


async def test_touch_api_key_failure_does_not_break_authentication() -> None:
    """The touch is best-effort: a store that raises must not surface to the caller."""
    from huron.service.api.authorization import _touch_api_key

    class _ExplodingStore:
        async def get(self, key_id: str) -> ApiKeyRecord | None:
            raise AssertionError("not used by _touch_api_key")

        async def touch_last_used(self, key_id: str) -> None:
            raise RuntimeError("database is unreachable")

    # Must not raise.
    await _touch_api_key(_ExplodingStore(), "hk_abc123_supersecret")


# -- Per-request binding cache -------------------------------------------------


class _CountingRepository:
    def __init__(self, bindings: tuple[Binding, ...]) -> None:
        self.calls = 0
        self._bindings = bindings

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        self.calls += 1
        return self._bindings


def _fake_request(repository: object) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(repository=repository)),
        state=SimpleNamespace(),
    )


async def test_cached_bindings_for_queries_once_per_identifier_set_per_request() -> None:
    repository = _CountingRepository(())
    request = _fake_request(repository)
    identifiers = frozenset({"user:alice"})

    await cached_bindings_for(request, repository, identifiers)
    await cached_bindings_for(request, repository, identifiers)
    assert repository.calls == 1

    await cached_bindings_for(request, repository, frozenset({"user:bob"}))
    assert repository.calls == 2


async def test_cached_bindings_for_does_not_leak_across_requests() -> None:
    repository = _CountingRepository(())
    identifiers = frozenset({"user:alice"})

    await cached_bindings_for(_fake_request(repository), repository, identifiers)
    await cached_bindings_for(_fake_request(repository), repository, identifiers)
    assert repository.calls == 2


async def test_check_only_queries_bindings_once_even_when_called_twice() -> None:
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        effect=Effect.ALLOW,
    )
    repository = _CountingRepository((binding,))
    request = _fake_request(repository)
    principal = AuthPrincipal(subject="alice")

    await check(request, principal, "dataset.discover", Scope.system())
    await check(request, principal, "dataset.discover", Scope.system())

    assert repository.calls == 1
