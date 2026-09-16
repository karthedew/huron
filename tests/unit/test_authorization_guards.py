"""The dependencies a route declares, proved against a real repository and granted RBAC roles.

Covers the four ``require_*`` factories and the ingest-session guards
(``dataset_raw_writer``, ``project_intake``, ``session_overseer``,
``session_owner``), including that an unknown or invisible scope answers
404 before any binding or layer check runs, and that a principal's kind
refuses a raw write before any binding is even consulted. Exercising these
also drives ``scopes.py``'s three resolvers, which have no test module of
their own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from huron.applications.api.authorization.guards import (
    dataset_raw_writer,
    project_intake,
    require_dataset,
    require_organization,
    require_project,
    require_system,
    session_overseer,
    session_owner,
)
from huron.core.raw._impl.ingest import IngestService
from huron.core.foundation.retry import request_sha256, IdempotencyClaim
from huron.core.security.principal import Principal
from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.errors import Forbidden
from huron.core.catalog.layers import LayerWriteForbidden
from huron.core.raw.manifest import ManifestEntry
from huron.core.metastore import (
    InMemoryHierarchyStore,
    InMemoryRbacStore,
    SystemClock,
)
from huron.core.rawstore import PosixRawStore
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
        PosixRawStore(str(tmp_path / "raw")),
        InMemoryHierarchyStore(),
        InMemoryRbacStore(),
    )


def _stack(tmp_path: Path) -> tuple[RepositoryFixture, IngestService]:
    """A repository and an ingest service sharing one raw store and hierarchy store."""
    hierarchy = InMemoryHierarchyStore()
    raw_store = PosixRawStore(str(tmp_path / "raw"))
    repository = RepositoryFixture(raw_store, hierarchy, InMemoryRbacStore())
    return repository, IngestService(raw_store, hierarchy, clock=SystemClock())


def _claim(operation: str, *parts: str | None, key: str) -> IdempotencyClaim:
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


# -- dataset_raw_writer: the scope, then the layer rule, then the binding -------


async def test_dataset_raw_writer_returns_the_principal_when_both_stages_pass(
    tmp_path: Path,
) -> None:
    """``dataset_raw_writer`` returns the principal once the scope, layer rule and binding pass."""
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

    result = await dataset_raw_writer(
        dataset_id=dataset.id,
        principal=alice,
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        cache={},
        visibility=Visibility.ALL,
    )

    assert result is alice


async def test_dataset_raw_writer_refuses_a_service_account_before_any_binding_is_checked(
    tmp_path: Path,
) -> None:
    """A service account is refused by the kind rule, whatever bindings it might otherwise hold.

    The layer rule is defense in depth: even a mis-seeded binding must not
    let a service account commit to raw.
    """
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    pipeline = Principal(subject="pipeline", kind="service_account")

    with pytest.raises(LayerWriteForbidden):
        await dataset_raw_writer(
            dataset_id=dataset.id,
            principal=pipeline,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_dataset_raw_writer_refuses_a_human_with_no_covering_binding(
    tmp_path: Path,
) -> None:
    """A human principal who is not the kind rule's problem is still refused with no binding."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    alice = Principal(subject="alice")

    with pytest.raises(Forbidden):
        await dataset_raw_writer(
            dataset_id=dataset.id,
            principal=alice,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_dataset_raw_writer_raises_not_found_for_an_unknown_dataset_before_the_layer_rule(
    tmp_path: Path,
) -> None:
    """An unknown dataset is 404 from the scope resolution, before the kind rule ever runs.

    A service-account caller would raise ``LayerWriteForbidden`` if the
    kind rule ran first; resolving the scope first means an unknown
    dataset is 404 instead, regardless of the caller's kind.
    """
    repository = _repository(tmp_path)
    pipeline = Principal(subject="pipeline", kind="service_account")

    with pytest.raises(ResourceNotFound):
        await dataset_raw_writer(
            dataset_id=uuid4(),
            principal=pipeline,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


# -- project_intake: the layer rule, then the raw-write binding, then dataset.create --


async def test_project_intake_returns_the_principal_when_every_stage_passes(tmp_path: Path) -> None:
    """A developer, who holds both ``data.write@raw`` and ``dataset.create``, may intake."""
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

    result = await project_intake(
        project_id=project.id,
        principal=alice,
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        cache={},
        visibility=Visibility.ALL,
    )

    assert result is alice


async def test_project_intake_refuses_a_service_account_before_dataset_create_is_checked(
    tmp_path: Path,
) -> None:
    """A service account is refused by the kind rule before ``dataset.create`` is ever asked.

    A service account's dataset-CRUD authority is intrinsic (it may mint a
    dataset directly), so if ``dataset.create`` ran first it would pass;
    the kind rule running first means it never mints a raw-entry dataset
    it could not then fill.
    """
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    pipeline = Principal(subject="pipeline", kind="service_account")

    with pytest.raises(LayerWriteForbidden):
        await project_intake(
            project_id=project.id,
            principal=pipeline,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_project_intake_refuses_a_human_with_no_covering_binding(tmp_path: Path) -> None:
    """A human with no raw-write binding is refused, never reaching the ``dataset.create`` check."""
    repository = _repository(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    alice = Principal(subject="alice")

    with pytest.raises(Forbidden):
        await project_intake(
            project_id=project.id,
            principal=alice,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_project_intake_raises_not_found_for_an_unknown_project_before_the_layer_rule(
    tmp_path: Path,
) -> None:
    """An unknown project is 404 from the scope resolution, before the kind rule ever runs."""
    repository = _repository(tmp_path)
    pipeline = Principal(subject="pipeline", kind="service_account")

    with pytest.raises(ResourceNotFound):
        await project_intake(
            project_id=uuid4(),
            principal=pipeline,
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            cache={},
            visibility=Visibility.ALL,
        )


# -- session_overseer and session_owner: the owner, or a project admin who may only read ---


async def _opened_session(ingest: IngestService, dataset: Dataset, *, created_by: str) -> UUID:
    """Open a session as ``created_by`` on ``dataset`` and return its id."""
    files = (ManifestEntry(path="payload/a.bin", size=5, sha256="a" * 64),)
    claim = IdempotencyClaim(
        principal=created_by,
        key=f"open-{dataset.id}",
        request_sha256=request_sha256("ingest_session", str(dataset.id)),
    )
    ledger = await ingest.create(dataset, files=files, created_by=created_by, claim=claim)
    return ledger.id


async def test_session_overseer_lets_the_owner_and_a_project_admin_read(tmp_path: Path) -> None:
    """The owner and a project admin both resolve, with ``owner`` distinguishing the two."""
    repository, ingest = _stack(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    await repository.rbac.grant_role(
        principal="user:carl",
        role_code="project_admin",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    session_id = await _opened_session(ingest, dataset, created_by="alice")

    as_owner = await session_overseer(
        session_id=session_id,
        principal=Principal(subject="alice"),
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        ingest=ingest,
        cache={},
        visibility=Visibility.ALL,
    )
    assert as_owner.owner is True

    as_admin = await session_overseer(
        session_id=session_id,
        principal=Principal(subject="carl"),
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        ingest=ingest,
        cache={},
        visibility=Visibility.ALL,
    )
    assert as_admin.owner is False


async def test_session_overseer_refuses_a_non_owner_without_project_update(tmp_path: Path) -> None:
    """A non-owner developer, who lacks ``project.update``, is refused."""
    repository, ingest = _stack(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    await repository.rbac.grant_role(
        principal="user:carl",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    session_id = await _opened_session(ingest, dataset, created_by="alice")

    with pytest.raises(Forbidden):
        await session_overseer(
            session_id=session_id,
            principal=Principal(subject="carl"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            ingest=ingest,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_session_overseer_raises_not_found_for_an_unknown_session(tmp_path: Path) -> None:
    """An id naming no session is 404, not a domain error about a missing dataset."""
    repository, ingest = _stack(tmp_path)

    with pytest.raises(ResourceNotFound):
        await session_overseer(
            session_id=uuid4(),
            principal=Principal(subject="alice"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            ingest=ingest,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_session_owner_refuses_a_project_admin_who_is_not_the_owner(tmp_path: Path) -> None:
    """A project admin may overseer a session but may not drive it: administering is not driving."""
    repository, ingest = _stack(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    await repository.rbac.grant_role(
        principal="user:carl",
        role_code="project_admin",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    session_id = await _opened_session(ingest, dataset, created_by="alice")

    with pytest.raises(Forbidden):
        await session_owner(
            session_id=session_id,
            principal=Principal(subject="carl"),
            repository=repository.rbac,
            hierarchy=repository.hierarchy,
            ingest=ingest,
            cache={},
            visibility=Visibility.ALL,
        )


async def test_session_owner_returns_the_drive_for_the_owner(tmp_path: Path) -> None:
    """The owner, whose raw-write binding still stands, may drive their own session."""
    repository, ingest = _stack(tmp_path)
    organization = await _organization(repository)
    project = await _project(repository, organization.id)
    dataset = await _dataset(repository, project.id)
    await repository.rbac.grant_role(
        principal="user:alice",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="admin",
    )
    session_id = await _opened_session(ingest, dataset, created_by="alice")

    drive = await session_owner(
        session_id=session_id,
        principal=Principal(subject="alice"),
        repository=repository.rbac,
        hierarchy=repository.hierarchy,
        ingest=ingest,
        cache={},
        visibility=Visibility.ALL,
    )

    assert drive.owner is True
    assert drive.ledger.id == session_id
