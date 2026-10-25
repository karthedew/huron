"""Reusable core workflows enforce ownership and authorization without an HTTP application."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from huron.core.catalog import (
    CatalogCreation,
    DatasetCollection,
    OrganizationCollection,
    ProjectCollection,
)
from huron.core.foundation.errors import Forbidden, ResourceNotFound
from huron.core.foundation.retry import IdempotencyClaim
from huron.core.metastore import InMemoryHierarchyStore, InMemoryRbacStore
from huron.core.rawstore import PosixGenerationStore
from huron.core.security import AccessPolicy, Bindings
from huron.core.security.principal import Principal
from huron.core.security.rules import Classification, RoleBindingAuthorizer, ScopeType
from tests.repository_fixture import RepositoryFixture

if TYPE_CHECKING:
    from pathlib import Path

    from huron.core.catalog.types import Dataset

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Clock:
    """A deterministic clock for hierarchy operations and idempotency claims."""

    def now(self) -> datetime:
        """Return a fixed instant."""
        return datetime(2026, 1, 1, tzinfo=UTC)


def claim(key: str, subject: str = "root") -> IdempotencyClaim:
    """Return a stable idempotency identity for one submitted operation."""
    return IdempotencyClaim(
        principal=subject, key=key, request_sha256=hashlib.sha256(key.encode()).hexdigest()
    )


@pytest.fixture
async def workspace(
    tmp_path: Path,
) -> tuple[
    OrganizationCollection,
    ProjectCollection,
    DatasetCollection,
    Bindings,
    AccessPolicy,
    Dataset,
    RepositoryFixture,
    InMemoryHierarchyStore,
    CatalogCreation,
]:
    """Wire real domain, core and POSIX objects without importing the FastAPI application."""
    storage = PosixGenerationStore(tmp_path / "raw")
    hierarchy = InMemoryHierarchyStore(clock=Clock())
    repository = RepositoryFixture(storage, hierarchy, InMemoryRbacStore())
    await repository.rbac.grant_role(
        principal="user:root",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="bootstrap",
    )
    access = AccessPolicy(
        Principal("root"),
        repository.hierarchy,
        repository.rbac,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    organizations = OrganizationCollection(access, repository.hierarchy, repository.raw_store)
    projects = ProjectCollection(access, repository.hierarchy, repository.raw_store)
    datasets = DatasetCollection(access, repository.hierarchy, repository.raw_store)
    bindings = Bindings(access, repository.hierarchy, repository.rbac)
    creation = CatalogCreation(
        access, repository.hierarchy, repository.raw_store, classification_vocabulary=("open",)
    )
    org = await creation.create_organization(
        slug="science", title="Science", description="", claim=claim("org")
    )
    project = await creation.create_project(
        org.id,
        slug="field",
        title="Field",
        description="",
        data_classification="open",
        claim=claim("project"),
    )
    await bindings.grant_role(
        principal="user:root",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
    )
    dataset = await creation.create_dataset(
        project.id,
        slug="samples",
        title="Samples",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim("dataset"),
    )
    return (
        organizations,
        projects,
        datasets,
        bindings,
        access,
        dataset,
        repository,
        hierarchy,
        creation,
    )


async def test_catalog_does_not_accept_a_foreign_claim(workspace) -> None:
    """Every create rejects a claim naming someone other than the authenticated actor."""
    _, projects, _, _, _, dataset, _, _, creation = workspace
    org = await projects.get(dataset.project_id)
    for operation in (
        creation.create_organization(
            slug="other", title="Other", description="", claim=claim("o", "other")
        ),
        creation.create_project(
            org.organization_id,
            slug="other",
            title="Other",
            description="",
            data_classification="open",
            claim=claim("p", "other"),
        ),
        creation.create_dataset(
            dataset.project_id,
            slug="other",
            title="Other",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=claim("d", "other"),
        ),
    ):
        with pytest.raises(Forbidden, match="idempotency"):
            await operation


async def test_core_cannot_create_or_discover_under_another_actor(workspace) -> None:
    """An actor with no bindings cannot mutate the catalog or discover its datasets."""
    _, _, _, _, _, dataset, repository, _, creation = workspace
    access = AccessPolicy(
        Principal("outsider"), repository.hierarchy, repository.rbac, RoleBindingAuthorizer()
    )
    datasets = DatasetCollection(access, repository.hierarchy, repository.raw_store)
    creation = CatalogCreation(
        access, repository.hierarchy, repository.raw_store, classification_vocabulary=("open",)
    )
    with pytest.raises(Forbidden, match=r"organization\.create denied"):
        await creation.create_organization(
            slug="other", title="Other", description="", claim=claim("other", "forged")
        )
    with pytest.raises(ResourceNotFound):
        await creation.create_dataset(
            dataset.project_id,
            slug="other",
            title="Other",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=claim("invisible", "forged"),
        )
    with pytest.raises(ResourceNotFound):
        await datasets.get(dataset.id)
    with pytest.raises(ValueError):
        await access.scope(ScopeType.PROJECT)


async def test_collections_read_and_page_with_current_narrow_grants(workspace) -> None:
    """Narrow discovery admits ancestors and granted datasets until the binding is revoked."""
    from huron.core.catalog.types import PlatformRoot
    from huron.core.security.rules import Visibility

    (
        root_organizations,
        root_projects,
        _,
        bindings,
        _,
        dataset,
        repository,
        hierarchy,
        creation,
    ) = workspace
    project = await root_projects.get(dataset.project_id)
    organization = await root_organizations.get(project.organization_id)
    sibling = await creation.create_dataset(
        project.id,
        slug="a-hidden",
        title="Hidden",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim("hidden-sibling"),
    )
    grant = await bindings.grant_role(
        principal="user:reader",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
    )
    access = AccessPolicy(
        Principal("reader"),
        hierarchy,
        repository.rbac,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    organizations = OrganizationCollection(access, hierarchy, repository.raw_store)
    projects = ProjectCollection(access, hierarchy, repository.raw_store)
    datasets = DatasetCollection(access, hierarchy, repository.raw_store)
    assert (await access.visibility()).project_ids == frozenset()
    assert await datasets.get(dataset.id) == dataset
    assert await projects.get(project.id) == project
    assert await organizations.get(organization.id) == organization
    assert (await access.scope(ScopeType.DATASET, dataset.id)).organization_id == organization.id
    for collection, parent, item in (
        (organizations, PlatformRoot.ROOT, organization),
        (projects, organization.id, project),
        (datasets, project.id, dataset),
    ):
        page = await collection.browse(parent, limit=1, after=None)
        assert page.items == [item]
        assert not page.has_more
        assert (await collection.browse(parent, limit=1, after=(item.slug, item.id))).items == []
    with pytest.raises(ResourceNotFound):
        await datasets.get(sibling.id)
    await bindings.revoke_role(grant.id)
    assert await access.visibility() == Visibility()
    for collection, resource_id in (
        (organizations, organization.id),
        (projects, project.id),
        (datasets, dataset.id),
    ):
        with pytest.raises(ResourceNotFound):
            await collection.get(resource_id)
    assert (await organizations.browse(PlatformRoot.ROOT, limit=1, after=None)).items == []
    for collection, parent in ((projects, organization.id), (datasets, project.id)):
        with pytest.raises(ResourceNotFound):
            await collection.browse(parent, limit=1, after=None)


async def test_collections_refuse_absent_parents_before_empty_pages(workspace) -> None:
    """A platform owner receives not found for missing child-browse parents and point targets."""
    organizations, projects, datasets, _, _, _, _, _, _ = workspace
    for collection in (projects, datasets):
        with pytest.raises(ResourceNotFound):
            await collection.browse(uuid4(), limit=10, after=None)
    for collection in (organizations, projects, datasets):
        with pytest.raises(ResourceNotFound):
            await collection.get(uuid4())


@pytest.mark.parametrize("kind", ("organization", "project", "dataset"))
async def test_descriptions_preserve_noop_validation_and_empty_replacements(
    workspace, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A no-op avoids transactions while stale and renamed requests fail before any write."""
    from huron.core.catalog.errors import SlugImmutable
    from huron.core.catalog.types import DescriptionChange
    from huron.core.foundation.errors import PreconditionFailed

    organizations, projects, datasets, _, _, dataset, _, hierarchy, _ = workspace
    project = await projects.get(dataset.project_id)
    organization = await organizations.get(project.organization_id)
    collection, item = {
        "organization": (organizations, organization),
        "project": (projects, project),
        "dataset": (datasets, dataset),
    }[kind]

    def unexpected_transaction():
        raise AssertionError("no-op and invalid descriptions must not open a transaction")

    with monkeypatch.context() as patch:
        patch.setattr(hierarchy, "transaction", unexpected_transaction)
        assert await collection.describe(item.id, DescriptionChange(item.version)) == item
        assert (
            await collection.describe(
                item.id,
                DescriptionChange(item.version, slug=item.slug, title=item.title),
            )
            == item
        )
        with pytest.raises(PreconditionFailed):
            await collection.describe(item.id, DescriptionChange(item.version + 1))
        with pytest.raises(SlugImmutable):
            await collection.describe(item.id, DescriptionChange(item.version + 1, slug="renamed"))
    changed = await collection.describe(item.id, DescriptionChange(item.version, title=""))
    assert changed.title == ""
    assert changed.description == item.description
    assert changed.version == item.version + 1
    assert changed.generation == item.generation + 1
    assert await collection.get(item.id) == changed


async def test_descriptions_require_authority_beyond_discovery(workspace) -> None:
    """A narrow reader can discover every ancestor but cannot describe any of those resources."""
    from huron.core.catalog.types import DescriptionChange

    _, projects, _, bindings, _, dataset, repository, hierarchy, _ = workspace
    project = await projects.get(dataset.project_id)
    grant = await bindings.grant_role(
        principal="user:reader",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
    )
    access = AccessPolicy(
        Principal("reader"),
        hierarchy,
        repository.rbac,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    reader_organizations = OrganizationCollection(access, hierarchy, repository.raw_store)
    reader_projects = ProjectCollection(access, hierarchy, repository.raw_store)
    reader_datasets = DatasetCollection(access, hierarchy, repository.raw_store)
    for collection, resource_id in (
        (reader_organizations, project.organization_id),
        (reader_projects, project.id),
        (reader_datasets, dataset.id),
    ):
        current = await collection.get(resource_id)
        with pytest.raises(Forbidden):
            await collection.describe(
                resource_id, DescriptionChange(current.version, title="Denied")
            )
    await bindings.revoke_role(grant.id)
    with pytest.raises(ResourceNotFound):
        await reader_datasets.describe(dataset.id, DescriptionChange(1, title="Hidden"))
