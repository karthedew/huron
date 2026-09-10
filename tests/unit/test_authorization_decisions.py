"""Bindings, the per-request cache, the allow/deny call, and current_visibility.

Proved with fakes and a real repository. Covers cache lifetime,
service-account binding synthesis, ``check``'s pass/refuse behavior, and
``current_visibility``'s reduction of a caller's bindings against the
hierarchy's shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.applications.api.authorization.decisions import (
    as_rbac_principal,
    bindings_for_principal,
    check,
    current_visibility,
    request_binding_cache,
)
from huron.core._catalog import HierarchyRepository
from huron.core.access import AccessPolicy
from huron.core.idempotency import request_sha256
from huron.core.scopes import resource_scope
from huron.pkg.auth import Principal
from huron.pkg.catalog.failures import Forbidden
from huron.pkg.metastore import IdempotencyClaim, InMemoryHierarchyStore, InMemoryRbacStore
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import (
    Binding,
    Classification,
    Effect,
    RoleBindingAuthorizer,
    Scope,
    ScopeType,
    Visibility,
)
from huron.pkg.rbac import Principal as RbacPrincipal

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    """A real, filesystem-backed HierarchyRepository for the service-account synthesis tests."""
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


class _StaticRepository:
    """A fake repository whose ``bindings_for`` always returns the same fixed bindings.

    Exercises ``check``/``bindings_for_principal`` without a
    filesystem-backed ``HierarchyRepository``: its bindings never change.
    """

    def __init__(self, bindings: tuple[Binding, ...]) -> None:
        self._bindings = bindings

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        return self._bindings


# -- request_binding_cache: one dict per request, never shared ------------------


async def test_request_binding_cache_returns_a_fresh_dict_every_call() -> None:
    """``request_binding_cache`` mints a fresh, empty dict on every call."""
    first = await request_binding_cache()
    second = await request_binding_cache()
    assert first == {}
    assert second == {}
    assert first is not second


# -- as_rbac_principal ------------------------------------------------------------


def test_as_rbac_principal_carries_subject_groups_and_kind() -> None:
    """``as_rbac_principal`` maps a Principal's subject, groups and kind onto RbacPrincipal."""
    principal = Principal(subject="alice", groups=frozenset({"astro"}), kind="service_account")
    assert as_rbac_principal(principal) == RbacPrincipal(
        subject="alice", groups=frozenset({"astro"}), kind="service_account"
    )


# -- check: allow, refuse, and what the refusal names --------------------------


async def test_check_allows_silently_when_a_binding_grants_the_capability() -> None:
    """``check`` passes silently when a binding grants the capability at the right scope."""
    binding = Binding(
        principal="user:alice",
        capabilities=frozenset({"dataset.discover"}),
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        effect=Effect.ALLOW,
    )
    await check(
        {},
        _StaticRepository((binding,)),
        Principal(subject="alice"),
        "dataset.discover",
        Scope.system(),
    )


async def test_check_raises_forbidden_naming_capability_subject_and_scope() -> None:
    """A missing binding raises Forbidden naming the capability, subject and scope."""
    with pytest.raises(Forbidden) as excinfo:
        await check(
            {},
            _StaticRepository(()),
            Principal(subject="alice"),
            "dataset.discover",
            Scope.system(),
        )
    assert str(excinfo.value) == "dataset.discover denied for alice at SYSTEM scope"


async def test_check_names_the_layer_in_its_message_when_one_is_given() -> None:
    """Forbidden's message names the layer too when ``check`` is called with one."""
    dataset_id = uuid4()
    scope = Scope(ScopeType.DATASET, dataset_id, dataset_id=dataset_id)
    with pytest.raises(Forbidden) as excinfo:
        await check(
            {},
            _StaticRepository(()),
            Principal(subject="alice"),
            "data.write",
            scope,
            layer="bronze",
        )
    assert str(excinfo.value) == "data.write on layer bronze denied for alice at DATASET scope"


async def test_check_reuses_the_cache_across_two_calls_for_the_same_principal() -> None:
    """A second ``check`` call for the same principal reuses the cache instead of re-querying.

    The cache is the caller's to reuse across guards within one request:
    a second ``check`` call for the same principal must not re-query, even
    when the first call denied.
    """

    class _CountingRepository:
        """A fake repository counting how many times ``bindings_for`` is called."""

        def __init__(self) -> None:
            self.calls = 0

        async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
            self.calls += 1
            return ()

    repository = _CountingRepository()
    cache: dict[frozenset[str], tuple[Binding, ...]] = {}
    alice = Principal(subject="alice")

    with pytest.raises(Forbidden):
        await check(cache, repository, alice, "dataset.discover", Scope.system())
    with pytest.raises(Forbidden):
        await check(cache, repository, alice, "dataset.discover", Scope.system())

    assert repository.calls == 1


# -- bindings_for_principal: service-account synthesis -------------------------


async def test_bindings_for_principal_synthesizes_grants_for_a_live_service_account(
    tmp_path: Path,
) -> None:
    """A live service account gets synthesized bindings from ``bindings_for_principal``."""
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
    actor = RbacPrincipal(subject=account.subject, kind="service_account")

    bindings = await bindings_for_principal({}, repository, actor)

    assert bindings != ()


async def test_bindings_for_principal_synthesizes_nothing_for_a_disabled_service_account(
    tmp_path: Path,
) -> None:
    """A disabled service account gets no bindings from ``bindings_for_principal``."""
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
    await repository.disable_service_account(account.principal_id, disabled_at=account.created_at)
    actor = RbacPrincipal(subject=account.subject, kind="service_account")

    bindings = await bindings_for_principal({}, repository, actor)

    assert bindings == ()


async def test_bindings_for_principal_denies_a_service_account_with_no_account_row(
    tmp_path: Path,
) -> None:
    """A service-account principal with no matching account row gets no bindings.

    A service-account key that outlived its account resolves as a
    principal but must never inherit bindings from a row that no longer
    exists.
    """
    repository = _repository(tmp_path)
    actor = RbacPrincipal(subject="org/gone", kind="service_account")

    bindings = await bindings_for_principal({}, repository, actor)

    assert bindings == ()


# -- current_visibility ---------------------------------------------------


async def test_current_visibility_for_a_system_platform_owner_is_unrestricted(
    tmp_path: Path,
) -> None:
    """A SYSTEM-scope ``platform_owner`` binding makes ``current_visibility`` unrestricted."""
    repository = _repository(tmp_path)
    await repository.grant_role(
        principal="user:root",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="admin",
    )
    runtime = SimpleNamespace(authorizer=RoleBindingAuthorizer())

    visibility = await current_visibility({}, repository, Principal(subject="root"), runtime)

    assert visibility.unrestricted is True


async def test_current_visibility_for_a_project_scoped_reader_holds_exactly_that_project(
    tmp_path: Path,
) -> None:
    """A PROJECT-scope ``reader`` binding makes ``current_visibility`` hold exactly that project."""
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
    await repository.grant_role(
        principal="user:alice",
        role_code="reader",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    runtime = SimpleNamespace(
        authorizer=RoleBindingAuthorizer(classifications=(Classification("open", 0, True),))
    )

    visibility = await current_visibility({}, repository, Principal(subject="alice"), runtime)

    assert visibility.project_ids == frozenset({project.id})
    assert visibility.organization_ids == frozenset()
    assert visibility.dataset_ids == frozenset()
    assert visibility.unrestricted is False


async def test_current_visibility_for_a_dataset_scoped_reader_holds_that_dataset(
    tmp_path: Path,
) -> None:
    """A DATASET-scope binding makes ``current_visibility`` resolve and hold that dataset.

    Reaching the dataset's id requires ``dataset_parents`` to resolve its
    owning project, which ``current_visibility`` calls only because this
    binding is DATASET-scoped.
    """
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
    await repository.grant_role(
        principal="user:alice",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="admin",
    )
    runtime = SimpleNamespace(
        authorizer=RoleBindingAuthorizer(classifications=(Classification("open", 0, True),))
    )

    visibility = await current_visibility({}, repository, Principal(subject="alice"), runtime)

    assert visibility.dataset_ids == frozenset({dataset.id})
    assert visibility.project_ids == frozenset()
    assert visibility.unrestricted is False


async def test_current_visibility_for_a_caller_with_no_bindings_is_empty(tmp_path: Path) -> None:
    """A caller with no bindings at all gets an empty ``Visibility``."""
    repository = _repository(tmp_path)
    runtime = SimpleNamespace(authorizer=RoleBindingAuthorizer())

    visibility = await current_visibility({}, repository, Principal(subject="nobody"), runtime)

    assert visibility == Visibility()


async def test_core_discovery_reloads_revoked_bindings_while_a_request_keeps_its_cache(
    tmp_path: Path,
) -> None:
    """Revocation applies on the next core operation and request; cached bindings stay unchanged."""
    repository = _repository(tmp_path)
    binding = await repository.grant_role(
        principal="user:alice",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    runtime = SimpleNamespace(authorizer=RoleBindingAuthorizer())
    access = AccessPolicy(alice, repository, runtime.authorizer)
    cache = await request_binding_cache()
    assert (await current_visibility(cache, repository, alice, runtime)).unrestricted
    assert (await access.visibility()).unrestricted

    await repository.revoke_role(binding.id)

    assert (await current_visibility(cache, repository, alice, runtime)).unrestricted
    assert await current_visibility({}, repository, alice, runtime) == Visibility()
    assert await access.visibility() == Visibility()
    with pytest.raises(Forbidden):
        await access.require("organization.create", ScopeType.SYSTEM)
    assert await current_visibility(cache, repository, Principal("bob"), runtime) == Visibility()


async def test_resource_scope_refuses_system_scope_with_a_resource_id(tmp_path: Path) -> None:
    """System authority cannot be resolved as a catalog resource."""
    with pytest.raises(ValueError, match="system scope has no catalog resource"):
        await resource_scope(_repository(tmp_path), ScopeType.SYSTEM, uuid4(), Visibility.ALL)
