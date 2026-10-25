"""Resource guards resolve discovery before checking the caller’s capability."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from huron.applications.api.authorization.guards import (
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from huron.core.foundation.errors import Forbidden, ResourceNotFound
from huron.core.foundation.retry import IdempotencyClaim, request_sha256
from huron.core.metastore import (
    InMemoryHierarchyStore,
    InMemoryRbacStore,
)
from huron.core.rawstore import PosixGenerationStore
from huron.core.security.principal import Principal
from huron.core.security.rules import ScopeType, Visibility
from tests.catalog_creation_support import creation_for
from tests.repository_fixture import RepositoryFixture

if TYPE_CHECKING:
    from pathlib import Path

    from huron.core.catalog.types import Dataset, Organization, Project

pytestmark = pytest.mark.unit


def _repository(tmp_path: Path) -> RepositoryFixture:
    """A real, filesystem-backed storage bundle for the guard tests."""
    return RepositoryFixture(
        PosixGenerationStore(tmp_path / "raw"),
        InMemoryHierarchyStore(),
        InMemoryRbacStore(),
    )


def _claim(operation: str, *parts: str, key: str) -> IdempotencyClaim:
    """Build an idempotency claim staked by ``tester`` over one operation's digest parts."""
    return IdempotencyClaim(
        principal="tester", key=key, request_sha256=request_sha256(operation, *parts)
    )


async def _organization(repository: RepositoryFixture) -> Organization:
    """An organization named ``astro``, created fresh in the given repository."""
    return await (await creation_for(repository)).create_organization(
        slug="astro",
        title="Astro",
        description="",
        claim=_claim("organization", "astro", "Astro", "", key="org-1"),
    )


async def _project(repository: RepositoryFixture, organization_id: UUID) -> Project:
    """A project named ``sims``, created under the given organization."""
    return await (await creation_for(repository)).create_project(
        organization_id,
        slug="sims",
        title="Sims",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization_id), "sims", "Sims", "", "open", key="proj-1"),
    )


async def _dataset(repository: RepositoryFixture, project_id: UUID) -> Dataset:
    """A dataset named ``run-0001``, created under the given project."""
    return await (await creation_for(repository)).create_dataset(
        project_id,
        slug="run-0001",
        title="Run 1",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=_claim(
            "dataset",
            str(project_id),
            "run-0001",
            "Run 1",
            "",
            "mcnp-run",
            "1.0",
            "raw",
            key="ds-1",
        ),
    )


# -- require_system -----------------------------------------------------------


async def test_require_system_returns_the_principal_when_a_binding_grants_the_capability(
    tmp_path: Path,
) -> None:
    """``require_system`` returns the principal when a SYSTEM-scope binding grants it."""
    repository = _repository(tmp_path)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_system("organization.create")

    result = await guard(principal=alice, repository=repository.rbac, cache={})

    assert result is alice


async def test_require_system_refuses_a_principal_with_no_binding(tmp_path: Path) -> None:
    """``require_system`` refuses a principal with no binding granting the capability."""
    repository = _repository(tmp_path)
    guard = require_system("organization.create")

    with pytest.raises(Forbidden):
        await guard(principal=Principal(subject="alice"), repository=repository.rbac, cache={})


# -- require_organization -------------------------------------------------------


async def test_require_organization_returns_the_principal_when_scoped_to_that_organization(
    tmp_path: Path,
) -> None:
    """``require_organization`` returns the principal when bound at that exact organization."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="organization_admin",
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_organization("service_account.manage")

    result = await guard(
        resource_id=organization.id,
        principal=alice,
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        cache={},
        visibility=Visibility.ALL,
    )

    assert result is alice


async def test_require_organization_raises_not_found_before_checking_the_binding(
    tmp_path: Path,
) -> None:
    """An unknown organization id raises 404 before the binding is ever checked.

    404 before 403: an unknown organization id must not leak its
    existence through a permission error, even for an unbound caller.
    """
    repository = _repository(tmp_path)
    guard = require_organization("service_account.manage")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_require_organization_raises_not_found_for_an_organization_the_caller_cannot_see(
    tmp_path: Path,
) -> None:
    """An organization outside the caller's visibility is 404, even with a covering binding.

    404 before 403 also covers the invisible, not only the absent: a
    binding at the right scope is irrelevant if the resource itself is
    outside what the caller may discover.
    """
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="organization_admin",
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization.id,
        created_by="admin",
    )
    guard = require_organization("service_account.manage")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=organization.id,
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility(),
        )


# -- require_project -------------------------------------------------------------


async def test_require_project_returns_the_principal_when_scoped_to_that_project(
    tmp_path: Path,
) -> None:
    """``require_project`` returns the principal when bound at that exact project."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_project("dataset.create")

    result = await guard(
        resource_id=project.id,
        principal=alice,
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        cache={},
        visibility=Visibility.ALL,
    )

    assert result is alice


async def test_require_project_refuses_a_binding_scoped_to_a_different_project(
    tmp_path: Path,
) -> None:
    """A binding scoped to one project does not authorize a guard for a different project."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    bound_project = await _project(repository, organization.id)
    other_project = await (await creation_for(repository)).create_project(
        organization.id,
        slug="other",
        title="Other",
        description="",
        data_classification="open",
        claim=_claim("project", str(organization.id), "other", "Other", "", "open", key="proj-2"),
    )
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=bound_project.id,
        created_by="admin",
    )
    guard = require_project("dataset.create")

    with pytest.raises(Forbidden):
        await guard(
            resource_id=other_project.id,
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_require_project_raises_not_found_for_an_unknown_project(tmp_path: Path) -> None:
    """``require_project`` raises 404 for a project id that does not exist."""
    repository = _repository(tmp_path)
    guard = require_project("dataset.create")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_require_project_raises_not_found_for_a_project_the_caller_cannot_see(
    tmp_path: Path,
) -> None:
    """A project outside the caller's visibility is 404, even with a covering binding."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    guard = require_project("dataset.create")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=project.id,
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility(),
        )


# -- require_dataset --------------------------------------------------------------


async def test_require_dataset_returns_the_principal_when_scoped_to_that_dataset(
    tmp_path: Path,
) -> None:
    """``require_dataset`` returns the principal when bound at that exact dataset."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="admin",
    )
    alice = Principal(subject="alice")
    guard = require_dataset("dataset.update")

    result = await guard(
        resource_id=dataset.id,
        principal=alice,
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        cache={},
        visibility=Visibility.ALL,
    )

    assert result is alice


async def test_require_dataset_raises_not_found_for_an_unknown_dataset(tmp_path: Path) -> None:
    """``require_dataset`` raises 404 for a dataset id that does not exist."""
    repository = _repository(tmp_path)
    guard = require_dataset("dataset.update")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_require_dataset_raises_not_found_for_a_dataset_the_caller_cannot_see(
    tmp_path: Path,
) -> None:
    """A dataset outside the caller's visibility is 404, even for a caller with a binding elsewhere.

    An invisible dataset is 404 from ``require_dataset`` for a caller who
    holds a binding at some other scope entirely, not only for one with no
    bindings at all.
    """
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    other_organization = await (await creation_for(repository)).create_organization(
        slug="biolab",
        title="Biolab",
        description="",
        claim=_claim("organization", "biolab", "Biolab", "", key="org-2"),
    )
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="organization_admin",
        scope_type=ScopeType.ORGANIZATION,
        scope_id=other_organization.id,
        created_by="admin",
    )
    guard = require_dataset("dataset.update")

    with pytest.raises(ResourceNotFound):
        await guard(
            resource_id=dataset.id,
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility(organization_ids=frozenset({other_organization.id})),
        )
