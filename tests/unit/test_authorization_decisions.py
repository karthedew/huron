"""Bindings, the per-request cache, and the allow/deny call: cache lifetime,
service-account synthesis, and ``check``'s pass/refuse behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.pkg.auth import Principal
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Binding, Effect, Scope, ScopeType
from huron.pkg.rbac import Principal as RbacPrincipal
from huron.service.api.authorization.decisions import (
    as_rbac_principal,
    bindings_for_principal,
    check,
    request_binding_cache,
)
from huron.service.api.errors import Forbidden
from huron.service.api.repository import HierarchyRepository

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")), classification_vocabulary=("open",)
    )


class _StaticRepository:
    """Exercises ``check``/``bindings_for_principal`` without a
    filesystem-backed ``HierarchyRepository``: its bindings never change."""

    def __init__(self, bindings: tuple[Binding, ...]) -> None:
        self._bindings = bindings

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        return self._bindings


# -- request_binding_cache: one dict per request, never shared ------------------


async def test_request_binding_cache_returns_a_fresh_dict_every_call() -> None:
    first = await request_binding_cache()
    second = await request_binding_cache()
    assert first == {}
    assert second == {}
    assert first is not second


# -- as_rbac_principal ------------------------------------------------------------


def test_as_rbac_principal_carries_subject_groups_and_kind() -> None:
    principal = Principal(subject="alice", groups=frozenset({"astro"}), kind="service_account")
    assert as_rbac_principal(principal) == RbacPrincipal(
        subject="alice", groups=frozenset({"astro"}), kind="service_account"
    )


# -- check: allow, refuse, and what the refusal names --------------------------


async def test_check_allows_silently_when_a_binding_grants_the_capability() -> None:
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
    """The cache is the caller's to reuse across guards within one request:
    a second ``check`` call for the same principal must not re-query, even
    when the first call denied."""

    class _CountingRepository:
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
    repository = _repository(tmp_path)
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
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
    repository = _repository(tmp_path)
    organization = repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="k1"
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
    """A service-account key that outlived its account resolves as a
    principal but must never inherit bindings from a row that no longer
    exists."""
    repository = _repository(tmp_path)
    actor = RbacPrincipal(subject="org/gone", kind="service_account")

    bindings = await bindings_for_principal({}, repository, actor)

    assert bindings == ()
