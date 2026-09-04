"""Direct unit tests for the RBAC storage seam and its per-request binding cache.

Covers ``InMemoryRbacStore``, ``HierarchyRepository``'s delegation to it, the
API-key touch bookkeeping, and the per-request binding cache in
``authorization.check``/``bindings_for_principal``.

PostgresRbacStore and PostgresApiKeyStore are exercised only by
``tests/contract/test_rbac_store.py`` against a real database - asyncpg rows
are not worth faking here, and the SQL is the part a fake can't verify.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.pkg.auth import ApiKeyRecord, MemoryApiKeyStore
from huron.pkg.auth import Principal as AuthPrincipal
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import (
    Binding,
    Decision,
    Effect,
    Principal,
    Scope,
    ScopeType,
    Visibility,
    decide,
)
from huron.pkg.rbac.roles import PrincipalKindNotAllowed, ScopeNotBindable
from huron.service.api.authorization import bindings_for_principal, check
from huron.service.api.errors import AttachmentExists, BindingExists, ServiceAccountExists
from huron.service.api.repository import HierarchyRepository, request_sha256
from huron.service.api.stores import IdempotencyClaim, InMemoryHierarchyStore, InMemoryRbacStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    """Build a ``HierarchyRepository`` at ``tmp_path`` with only "open" classification allowed."""
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")),
        InMemoryHierarchyStore(),
        classification_vocabulary=("open",),
        rbac_store=InMemoryRbacStore(),
    )


def _claim(operation: str, *parts: str | None, key: str) -> IdempotencyClaim:
    """Build an idempotency claim staked by ``tester`` over one operation's digest parts."""
    return IdempotencyClaim(
        principal="tester", key=key, request_sha256=request_sha256(operation, *parts)
    )


# -- InMemoryRbacStore --------------------------------------------------------


async def test_grant_role_compiles_the_same_binding_shape_compile_binding_produces() -> None:
    """``grant_role`` compiles the same three-binding shape ``compile_binding`` produces."""
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
            principal="sa:astro/feed",
            role_code="reader",
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
    """Granting the identical principal/role/scope binding twice raises ``BindingExists``."""
    store = InMemoryRbacStore()
    scope_id = uuid4()
    await store.grant_role(
        principal="user:bob",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        created_by="alice",
    )
    with pytest.raises(BindingExists):
        await store.grant_role(
            principal="user:bob",
            role_code="reader",
            scope_type=ScopeType.PROJECT,
            scope_id=scope_id,
            created_by="alice",
        )


async def test_expired_binding_is_denied_by_decide() -> None:
    """A binding whose lease has already expired is denied by ``decide``."""
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
    """Revoking a role clears its bindings; further lookups raise ``ResourceNotFound``."""
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
    assert await store.get_role_binding(record.id) == record

    await store.revoke_role(record.id)

    assert await store.bindings_for(frozenset({"user:bob"})) == ()
    with pytest.raises(ResourceNotFound):
        await store.get_role_binding(record.id)
    with pytest.raises(ResourceNotFound):
        await store.revoke_role(record.id)


async def test_service_account_and_policy_listings_are_sorted_and_scoped() -> None:
    """Service-account listings are scoped by org; both listings sort by name."""
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

    with pytest.raises(ServiceAccountExists):
        await store.create_service_account(
            organization_id, name="alpha", subject="org/alpha-2", created_by="alice"
        )

    await store.create_policy(policy_type="retention", name="zzz", spec={}, created_by="alice")
    await store.create_policy(policy_type="retention", name="aaa", spec={}, created_by="alice")
    policies = await store.list_policies()
    assert [item.name for item in policies] == ["aaa", "zzz"]


async def test_get_service_account_and_disable_service_account_raise_when_missing() -> None:
    """``get_service_account`` and ``disable_service_account`` each refuse an unknown id."""
    store = InMemoryRbacStore()
    with pytest.raises(ResourceNotFound):
        await store.get_service_account(uuid4())
    with pytest.raises(ResourceNotFound):
        await store.disable_service_account(uuid4(), disabled_at=datetime.now(UTC))


async def test_attach_policy_rejects_unknown_policy_and_duplicate_attachment() -> None:
    """``attach_policy`` refuses an unknown policy and refuses attaching the same policy twice."""
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
    with pytest.raises(AttachmentExists):
        await store.attach_policy(
            policy.id, scope_type=ScopeType.ORGANIZATION, scope_id=scope_id, attached_by="alice"
        )


async def test_bindings_at_returns_system_scope_bindings_sorted_by_principal_then_role() -> None:
    """``bindings_at`` returns a scope's own bindings, sorted by principal."""
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
    """``grant_role`` raises ``ResourceNotFound`` for a scope id that does not exist."""
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
    """Granting at SYSTEM scope with a non-None ``scope_id`` raises ``ValueError``.

    No route can produce this - the SYSTEM binding routes always pass
    ``scope_id=None`` - so an inconsistent pair is a bug, not a client
    contract, and raises the plain ``ValueError`` the unhandled-exception
    path turns into a 500.
    """
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="SYSTEM scope takes no scope_id"):
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
    """Granting below SYSTEM scope with ``scope_id=None`` raises ``ValueError``."""
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="PROJECT scope requires a scope_id"):
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
    """A service account's subject is derived as ``{org slug}/{name}`` and round-trips."""
    repository = _repository(tmp_path)
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    account = await repository.create_service_account(
        organization.id, name="canonicalizer", created_by="alice"
    )
    assert account.subject == "astro/canonicalizer"
    fetched = await repository.get_service_account(account.principal_id)
    assert fetched == account


async def test_hierarchy_repository_checks_dataset_scope_existence_before_delegating(
    tmp_path: Path,
) -> None:
    """Granting, fetching and revoking a role at a real dataset's scope succeeds end to end."""
    repository = _repository(tmp_path)
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )
    project = await repository.create_project(
        organization.id,
        Visibility.ALL,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "sims", "Sims", "", "open", key="proj-1"),
    )
    dataset = await repository.create_dataset(
        project.id,
        Visibility.ALL,
        slug="run-0001",
        title="Run 1",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=_claim(
            "dataset",
            str(project.id),
            "run-0001",
            "Run 1",
            "",
            "mcnp-run",
            "1.0",
            "raw",
            key="ds-1",
        ),
    )

    record = await repository.grant_role(
        principal="user:bob",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="alice",
    )
    assert await repository.get_role_binding(record.id) == record
    assert await repository.revoke_role(record.id) == record
    with pytest.raises(ResourceNotFound):
        await repository.get_role_binding(record.id)


async def test_bindings_at_raises_for_an_unknown_scope(tmp_path: Path) -> None:
    """``bindings_at`` raises ``ResourceNotFound`` for a scope id that names nothing.

    An unknown scope used to answer an empty list, indistinguishable from a
    scope with no bindings; it now fails closed the same way every other
    hierarchy read does.
    """
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        await repository.bindings_at(ScopeType.PROJECT, uuid4())


async def test_list_service_accounts_raises_for_an_unknown_organization(tmp_path: Path) -> None:
    """``list_service_accounts`` raises ``ResourceNotFound`` for an unknown organization id."""
    repository = _repository(tmp_path)
    with pytest.raises(ResourceNotFound):
        await repository.list_service_accounts(uuid4())


async def test_hierarchy_repository_list_service_accounts_and_policies_delegate(
    tmp_path: Path,
) -> None:
    """``list_service_accounts`` and ``list_policies`` delegate correctly to the rbac store."""
    repository = _repository(tmp_path)
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-2"),
    )
    await repository.create_service_account(organization.id, name="loader", created_by="alice")
    accounts = await repository.list_service_accounts(organization.id)
    assert [item.name for item in accounts] == ["loader"]

    await repository.create_policy(
        policy_type="retention", name="raw-90d", spec={"days": 90}, created_by="alice"
    )
    policies = await repository.list_policies()
    assert [item.name for item in policies] == ["raw-90d"]


# -- API key touch bookkeeping -------------------------------------------------


async def test_memory_api_key_store_records_touch_calls() -> None:
    """``MemoryApiKeyStore.touch_last_used`` records the touched key id in call order."""
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
    from huron.service.api.authorization.credentials import _touch_api_key

    class _ExplodingStore:
        """An API-key store whose ``touch_last_used`` always raises."""

        async def get(self, key_id: str) -> ApiKeyRecord | None:
            raise AssertionError("not used by _touch_api_key")

        async def touch_last_used(self, key_id: str) -> None:
            raise RuntimeError("database is unreachable")

    # Must not raise.
    await _touch_api_key(_ExplodingStore(), "hk_abc123_supersecret")


# -- Per-request binding cache -------------------------------------------------


class _CountingRepository:
    """A fake repository whose ``bindings_for`` counts calls and returns the given bindings."""

    def __init__(self, bindings: tuple[Binding, ...]) -> None:
        self.calls = 0
        self._bindings = bindings

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        self.calls += 1
        return self._bindings


async def test_bindings_for_principal_queries_once_per_identifier_set_per_request() -> None:
    """Repeated calls for the same principal share the cache; a new principal queries again."""
    repository = _CountingRepository(())
    cache: dict[frozenset[str], tuple[Binding, ...]] = {}
    alice = Principal(subject="alice")

    await bindings_for_principal(cache, repository, alice)
    await bindings_for_principal(cache, repository, alice)
    assert repository.calls == 1

    await bindings_for_principal(cache, repository, Principal(subject="bob"))
    assert repository.calls == 2


async def test_bindings_for_principal_does_not_leak_across_requests() -> None:
    """A fresh cache means the same principal is queried again, not reused across requests."""
    repository = _CountingRepository(())
    alice = Principal(subject="alice")

    await bindings_for_principal({}, repository, alice)
    await bindings_for_principal({}, repository, alice)
    assert repository.calls == 2


async def test_check_only_queries_bindings_once_even_when_called_twice() -> None:
    """``check`` shares the binding-query cache across repeated calls for the same principal."""
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        effect=Effect.ALLOW,
    )
    repository = _CountingRepository((binding,))
    cache: dict[frozenset[str], tuple[Binding, ...]] = {}
    principal = AuthPrincipal(subject="alice")

    await check(cache, repository, principal, "dataset.discover", Scope.system())
    await check(cache, repository, principal, "dataset.discover", Scope.system())

    assert repository.calls == 1


async def test_bindings_for_principal_synthesizes_grants_for_a_live_service_account(
    tmp_path: Path,
) -> None:
    """``bindings_for_principal`` synthesizes non-empty grants for a live service account."""
    repository = _repository(tmp_path)
    organization = await repository.create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="k1"),
    )
    account = await repository.create_service_account(
        organization.id, name="feed", created_by="alice"
    )
    actor = Principal(subject=account.subject, kind="service_account")
    cache: dict[frozenset[str], tuple[Binding, ...]] = {}

    bindings = await bindings_for_principal(cache, repository, actor)

    assert bindings != ()
    assert actor.identifiers in cache


async def test_bindings_for_principal_denies_a_service_account_with_no_account_row(
    tmp_path: Path,
) -> None:
    """A service-account principal with no matching account row gets empty bindings, cached.

    A service-account key that outlived its account resolves as a
    principal but must never inherit bindings from a row that no longer
    exists.
    """
    repository = _repository(tmp_path)
    actor = Principal(subject="org/gone", kind="service_account")
    cache: dict[frozenset[str], tuple[Binding, ...]] = {}

    bindings = await bindings_for_principal(cache, repository, actor)

    assert bindings == ()
    assert cache[actor.identifiers] == ()
