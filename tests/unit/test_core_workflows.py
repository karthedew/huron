"""Reusable core workflows enforce ownership and authorization without an HTTP application."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import ValidationError

from huron.core._catalog import HierarchyRepository
from huron.core._ingest import IngestService
from huron.core._revision_reader import RevisionService
from huron.core.access import AccessPolicy
from huron.core.catalog import CatalogService
from huron.core.catalog_creation import CatalogCreation
from huron.core.raw import RawIngestionService
from huron.core.revisions import RevisionReadService
from huron.pkg.auth import Principal
from huron.pkg.catalog import FileState, ManifestEntry
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.failures import Forbidden
from huron.pkg.catalog.persistence import IdempotencyClaim
from huron.pkg.metastore import InMemoryHierarchyStore, InMemoryRbacStore
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Classification, RoleBindingAuthorizer, ScopeType

if TYPE_CHECKING:
    from pathlib import Path

    from huron.pkg.catalog.records import Dataset

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Clock:
    """A deterministic clock for uploads and their in-memory ledger."""

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
    CatalogService,
    RawIngestionService,
    AccessPolicy,
    Dataset,
    HierarchyRepository,
    InMemoryHierarchyStore,
    RevisionReadService,
    CatalogCreation,
]:
    """Wire real domain, core and POSIX objects without importing the FastAPI application."""
    storage = PosixRawStore(str(tmp_path / "raw"))
    hierarchy = InMemoryHierarchyStore(clock=Clock())
    repository = HierarchyRepository(storage, hierarchy, rbac_store=InMemoryRbacStore())
    await repository.grant_role(
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
    catalog = CatalogService(repository, access, repository.hierarchy)
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
    await repository.grant_role(
        principal="user:root",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        created_by="bootstrap",
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
    raw = RawIngestionService(IngestService(storage, hierarchy, clock=Clock()), access, creation)
    revisions = RevisionReadService(RevisionService(storage, hierarchy), access)
    return catalog, raw, access, dataset, repository, hierarchy, revisions, creation


async def test_catalog_does_not_accept_a_foreign_claim(workspace) -> None:
    """Every create rejects a claim naming someone other than the authenticated actor."""
    catalog, _, _, dataset, _, _, _, creation = workspace
    org = await catalog.projects.get(dataset.project_id)
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
        catalog.create_release(
            dataset.id,
            tag="v1",
            revision_number=1,
            title=None,
            created_by="root",
            claim=claim("r", "other"),
        ),
    ):
        with pytest.raises(Forbidden, match="idempotency"):
            await operation


async def test_core_cannot_create_or_discover_under_another_actor(workspace) -> None:
    """An actor with no bindings cannot mutate the catalog or discover its datasets."""
    _, _, _, dataset, repository, _, _, creation = workspace
    access = AccessPolicy(
        Principal("outsider"), repository.hierarchy, repository.rbac, RoleBindingAuthorizer()
    )
    catalog = CatalogService(repository, access, repository.hierarchy)
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
        await catalog.datasets.get(dataset.id)
    with pytest.raises(ValueError):
        await access.scope(ScopeType.PROJECT)


async def test_raw_checks_owner_target_metadata_and_revocation_before_commit(workspace) -> None:
    """Direct callers cannot spoof owners, mix files, forge metadata or commit after revocation."""
    catalog, raw, _access, dataset, repository, hierarchy, revisions, creation = workspace
    contents = b"field measurements"
    entry = ManifestEntry(
        path="payload/field.txt", size=len(contents), sha256=hashlib.sha256(contents).hexdigest()
    )
    with pytest.raises(Forbidden, match="idempotency"):
        await raw.create(dataset.id, files=[entry], claim=claim("bad", "other"))
    ledger = await raw.create(dataset.id, files=[entry], claim=claim("upload"))
    assert ledger.created_by == "root"
    assert (await raw.ledger(ledger.id)).dataset_id == dataset.id
    second = await creation.create_dataset(
        dataset.project_id,
        slug="second",
        title="Second",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim("second"),
    )
    other = await raw.create(second.id, files=[entry], claim=claim("other-upload"))
    file = ledger.files[0]
    for operation in (
        raw.receive_part(
            ledger.id, other.files[0].file_id, 1, [contents], content_length=len(contents)
        ),
        raw.complete_file(ledger.id, other.files[0].file_id),
    ):
        with pytest.raises(Forbidden, match="file does not belong"):
            await operation
    other_access = AccessPolicy(
        Principal("other"),
        repository.hierarchy,
        repository.rbac,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    stranger = RawIngestionService(
        IngestService(repository.raw_store, hierarchy, clock=Clock()),
        other_access,
        CatalogCreation(
            other_access,
            repository.hierarchy,
            repository.raw_store,
            classification_vocabulary=("open",),
        ),
    )
    await catalog.grant_role(
        principal="user:other",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="root",
    )
    assert (await stranger.ledger(ledger.id)).id == ledger.id
    for operation in (
        stranger.verify(ledger.id),
        stranger.receive_part(ledger.id, uuid4(), 1, [contents], content_length=len(contents)),
        stranger.complete_file(ledger.id, uuid4()),
        stranger.commit(
            ledger.id,
            expected_etag=ledger.etag,
            manifest_sha256=ledger.manifest_sha256,
            metadata={},
            claim=claim("unowned-commit", "forged"),
        ),
    ):
        with pytest.raises(Forbidden, match="owner"):
            await operation
    assert await raw.ledger(ledger.id) == ledger
    await raw.receive_part(ledger.id, file.file_id, 1, [contents], content_length=len(contents))
    completed = await raw.complete_file(ledger.id, file.file_id)
    assert completed.file_id == file.file_id
    assert completed.state is FileState.COMPLETE
    ledger = await raw.verify(ledger.id)
    args = dict(
        expected_etag=ledger.etag,
        manifest_sha256=ledger.manifest_sha256,
        metadata={"title": "Field", "creators": ["scientist"]},
        claim=claim("commit"),
    )
    with pytest.raises(Forbidden, match="idempotency"):
        await raw.commit(ledger.id, **(args | {"claim": claim("badcommit", "other")}))
    with pytest.raises(ValidationError):
        await raw.commit(ledger.id, **(args | {"metadata": {"title": "missing creators"}}))
    bindings = await catalog.bindings_at(ScopeType.PROJECT, dataset.project_id)
    root_binding = next(
        b for b in bindings if b.principal == "user:root" and b.role_code == "developer"
    )
    await catalog.revoke_role(root_binding.id)
    with pytest.raises((Forbidden, ResourceNotFound)):
        await raw.commit(ledger.id, **args)
    await repository.grant_role(
        principal="user:root",
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=dataset.project_id,
        created_by="bootstrap",
    )
    committed = await raw.commit(ledger.id, **args)
    assert committed.committed_by == "root"
    assert (await raw.commit(ledger.id, **args)).id == committed.id
    forged = replace(committed, revision_path="/etc")
    payload = await revisions.payload_file(forged, "payload/field.txt")
    assert payload.location.read_bytes() == contents
    assert (await revisions.revision(committed.id)).dataset_id == dataset.id


async def test_collections_read_and_page_with_current_narrow_grants(workspace) -> None:
    """Narrow discovery admits ancestors and granted datasets until the binding is revoked."""
    from huron.core.catalog_collections import (
        DatasetCollection,
        OrganizationCollection,
        ProjectCollection,
    )
    from huron.pkg.catalog.persistence import PlatformRoot
    from huron.pkg.rbac import Visibility

    catalog, _, _, dataset, repository, hierarchy, _, creation = workspace
    project = await catalog.projects.get(dataset.project_id)
    organization = await catalog.organizations.get(project.organization_id)
    sibling = await creation.create_dataset(
        project.id,
        slug="a-hidden",
        title="Hidden",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim("hidden-sibling"),
    )
    grant = await repository.grant_role(
        principal="user:reader",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="root",
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
    await repository.revoke_role(grant.id)
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
    catalog, _, _, _, _, _, _, _ = workspace
    for collection in (catalog.projects, catalog.datasets):
        with pytest.raises(ResourceNotFound):
            await collection.browse(uuid4(), limit=10, after=None)
    for collection in (catalog.organizations, catalog.projects, catalog.datasets):
        with pytest.raises(ResourceNotFound):
            await collection.get(uuid4())


@pytest.mark.parametrize("kind", ("organization", "project", "dataset"))
async def test_descriptions_preserve_noop_validation_and_empty_replacements(
    workspace, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A no-op avoids transactions while stale and renamed requests fail before any write."""
    from huron.core.catalog_collections import DescriptionChange
    from huron.pkg.catalog.errors import PreconditionFailed, SlugImmutable

    catalog, _, _, dataset, _, hierarchy, _, _ = workspace
    project = await catalog.projects.get(dataset.project_id)
    organization = await catalog.organizations.get(project.organization_id)
    collection, item = {
        "organization": (catalog.organizations, organization),
        "project": (catalog.projects, project),
        "dataset": (catalog.datasets, dataset),
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
    from huron.core.catalog_collections import DescriptionChange

    catalog, _, _, dataset, repository, hierarchy, _, _ = workspace
    project = await catalog.projects.get(dataset.project_id)
    grant = await repository.grant_role(
        principal="user:reader",
        role_code="reader",
        scope_type=ScopeType.DATASET,
        scope_id=dataset.id,
        created_by="root",
    )
    access = AccessPolicy(
        Principal("reader"),
        hierarchy,
        repository.rbac,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    reader = CatalogService(repository, access, hierarchy)
    for collection, resource_id in (
        (reader.organizations, project.organization_id),
        (reader.projects, project.id),
        (reader.datasets, dataset.id),
    ):
        current = await collection.get(resource_id)
        with pytest.raises(Forbidden):
            await collection.describe(
                resource_id, DescriptionChange(current.version, title="Denied")
            )
    await repository.revoke_role(grant.id)
    with pytest.raises(ResourceNotFound):
        await reader.datasets.describe(dataset.id, DescriptionChange(1, title="Hidden"))
