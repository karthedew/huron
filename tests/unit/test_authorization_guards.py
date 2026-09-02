"""The dependencies a route declares: the four ``require_*`` factories and
the layer-write two-stage rule. Exercising these also drives ``scopes.py``'s
three resolvers, which have no test module of their own."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from huron.pkg.auth import Principal
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.layers import Layer, LayerWriteForbidden
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import ScopeType
from huron.service.api.authorization.guards import (
    LayerWrite,
    dataset_layer_writer,
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from huron.service.api.errors import Forbidden
from huron.service.api.repository import HierarchyRepository

if TYPE_CHECKING:
    from pathlib import Path

    from huron.service.api.records import Dataset, Organization, Project

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> HierarchyRepository:
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")), classification_vocabulary=("open",)
    )


def _organization(repository: HierarchyRepository) -> Organization:
    return repository.create_organization(
        slug="astro", title="Astro", description="", idempotency_key="org-1"
    )


def _project(repository: HierarchyRepository, organization_id: UUID) -> Project:
    return repository.create_project(
        organization_id,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        idempotency_key="proj-1",
    )


def _dataset(repository: HierarchyRepository, project_id: UUID) -> Dataset:
    return repository.create_dataset(
        project_id,
        slug="run-0001",
        title="Run 1",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        idempotency_key="ds-1",
    )


# -- require_system -----------------------------------------------------------


async def test_require_system_returns_the_principal_when_a_binding_grants_the_capability(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    await repository.grant_role(
        principal="user:alice",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_system("organization.create")

    result = await guard(principal=alice, repository=repository, cache={})

    assert result is alice


async def test_require_system_refuses_a_principal_with_no_binding(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    guard = require_system("organization.create")

    with pytest.raises(Forbidden):
        await guard(principal=Principal(subject="alice"), repository=repository, cache={})


# -- require_organization -------------------------------------------------------


async def test_require_organization_returns_the_principal_when_scoped_to_that_organization(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    await repository.grant_role(
        principal="user:alice",
        role_code="organization_admin",
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_organization("service_account.manage")

    result = await guard(
        organization_id=organization.id, principal=alice, repository=repository, cache={}
    )

    assert result is alice


async def test_require_organization_raises_not_found_before_checking_the_binding(
    tmp_path: Path,
) -> None:
    """404 before 403: an unknown organization id must not leak its
    existence through a permission error, even for an unbound caller."""
    repository = _repository(tmp_path)
    guard = require_organization("service_account.manage")

    with pytest.raises(ResourceNotFound):
        await guard(
            organization_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository,
            cache={},
        )


# -- require_project -------------------------------------------------------------


async def test_require_project_returns_the_principal_when_scoped_to_that_project(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    project = _project(repository, organization.id)
    await repository.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_project("dataset.create")

    result = await guard(project_id=project.id, principal=alice, repository=repository, cache={})

    assert result is alice


async def test_require_project_refuses_a_binding_scoped_to_a_different_project(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    bound_project = _project(repository, organization.id)
    other_project = repository.create_project(
        organization.id,
        slug="other",
        title="Other",
        description="",
        data_classification="open",
        idempotency_key="proj-2",
    )
    await repository.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=bound_project.id,
        created_by="admin",
    )
    guard = require_project("dataset.create")

    with pytest.raises(Forbidden):
        await guard(
            project_id=other_project.id,
            principal=Principal(subject="alice"),
            repository=repository,
            cache={},
        )


async def test_require_project_raises_not_found_for_an_unknown_project(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    guard = require_project("dataset.create")

    with pytest.raises(ResourceNotFound):
        await guard(
            project_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository,
            cache={},
        )


# -- require_dataset --------------------------------------------------------------


async def test_require_dataset_returns_the_principal_when_scoped_to_that_dataset(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    project = _project(repository, organization.id)
    dataset = _dataset(repository, project.id)
    await repository.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_dataset("dataset.update")

    result = await guard(dataset_id=dataset.id, principal=alice, repository=repository, cache={})

    assert result is alice


async def test_require_dataset_raises_not_found_for_an_unknown_dataset(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    guard = require_dataset("dataset.update")

    with pytest.raises(ResourceNotFound):
        await guard(
            dataset_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository,
            cache={},
        )


# -- dataset_layer_writer: the layer rule, then the binding check -----------------


async def test_dataset_layer_writer_returns_a_layer_write_when_both_stages_pass(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    project = _project(repository, organization.id)
    dataset = _dataset(repository, project.id)
    await repository.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")

    result = await dataset_layer_writer(
        dataset_id=dataset.id, layer="raw", principal=alice, repository=repository, cache={}
    )

    assert result == LayerWrite(principal=alice, layer=Layer.RAW)


async def test_dataset_layer_writer_refuses_a_human_principal_on_silver_regardless_of_bindings(
    tmp_path: Path,
) -> None:
    """The layer rule runs before the binding check and is defense in depth:
    even a mis-seeded binding must not let a human commit to silver."""
    repository = _repository(tmp_path)
    organization = _organization(repository)
    project = _project(repository, organization.id)
    dataset = _dataset(repository, project.id)
    alice = Principal(subject="alice")

    with pytest.raises(LayerWriteForbidden):
        await dataset_layer_writer(
            dataset_id=dataset.id, layer="silver", principal=alice, repository=repository, cache={}
        )


async def test_dataset_layer_writer_refuses_a_writable_layer_with_no_binding(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    organization = _organization(repository)
    project = _project(repository, organization.id)
    dataset = _dataset(repository, project.id)
    alice = Principal(subject="alice")

    with pytest.raises(Forbidden):
        await dataset_layer_writer(
            dataset_id=dataset.id, layer="raw", principal=alice, repository=repository, cache={}
        )
