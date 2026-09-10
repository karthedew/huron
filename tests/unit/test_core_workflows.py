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
]:
    """Wire real domain, core and POSIX objects without importing the FastAPI application."""
    storage = PosixRawStore(str(tmp_path / "raw"))
    hierarchy = InMemoryHierarchyStore(clock=Clock())
    repository = HierarchyRepository(
        storage, hierarchy, classification_vocabulary=("open",), rbac_store=InMemoryRbacStore()
    )
    await repository.grant_role(
        principal="user:root",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="bootstrap",
    )
    access = AccessPolicy(
        Principal("root"), repository, RoleBindingAuthorizer((Classification("open", 0, True),))
    )
    catalog = CatalogService(repository, access)
    org = await catalog.create_organization(
        slug="science", title="Science", description="", claim=claim("org")
    )
    project = await catalog.create_project(
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
    dataset = await catalog.create_dataset(
        project.id,
        slug="samples",
        title="Samples",
        description="",
        profile_name="mcnp-run",
        profile_version="1.0",
        claim=claim("dataset"),
    )
    raw = RawIngestionService(IngestService(storage, hierarchy, clock=Clock()), access, catalog)
    revisions = RevisionReadService(RevisionService(storage, hierarchy), access)
    return catalog, raw, access, dataset, repository, hierarchy, revisions


async def test_catalog_does_not_accept_a_foreign_claim(workspace) -> None:
    """Every create rejects a claim naming someone other than the authenticated actor."""
    catalog, _, _, dataset, _, _, _ = workspace
    org = await catalog.project(dataset.project_id)
    for operation in (
        catalog.create_organization(
            slug="other", title="Other", description="", claim=claim("o", "other")
        ),
        catalog.create_project(
            org.organization_id,
            slug="other",
            title="Other",
            description="",
            data_classification="open",
            claim=claim("p", "other"),
        ),
        catalog.create_dataset(
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
    _, _, _, dataset, repository, _, _ = workspace
    access = AccessPolicy(Principal("outsider"), repository, RoleBindingAuthorizer())
    catalog = CatalogService(repository, access)
    with pytest.raises(Forbidden, match=r"organization\.create denied"):
        await catalog.create_organization(
            slug="other", title="Other", description="", claim=claim("other", "forged")
        )
    with pytest.raises(ResourceNotFound):
        await catalog.create_dataset(
            dataset.project_id,
            slug="other",
            title="Other",
            description="",
            profile_name="mcnp-run",
            profile_version="1.0",
            claim=claim("invisible", "forged"),
        )
    with pytest.raises(ResourceNotFound):
        await catalog.dataset(dataset.id)
    with pytest.raises(ValueError):
        await access.scope(ScopeType.PROJECT)


async def test_raw_checks_owner_target_metadata_and_revocation_before_commit(workspace) -> None:
    """Direct callers cannot spoof owners, mix files, forge metadata or commit after revocation."""
    catalog, raw, _access, dataset, repository, hierarchy, revisions = workspace
    contents = b"field measurements"
    entry = ManifestEntry(
        path="payload/field.txt", size=len(contents), sha256=hashlib.sha256(contents).hexdigest()
    )
    with pytest.raises(Forbidden, match="idempotency"):
        await raw.create(dataset.id, files=[entry], claim=claim("bad", "other"))
    ledger = await raw.create(dataset.id, files=[entry], claim=claim("upload"))
    assert ledger.created_by == "root"
    assert (await raw.ledger(ledger.id)).dataset_id == dataset.id
    second = await catalog.create_dataset(
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
        Principal("other"), repository, RoleBindingAuthorizer((Classification("open", 0, True),))
    )
    stranger = RawIngestionService(
        IngestService(repository.raw_store, hierarchy, clock=Clock()),
        other_access,
        CatalogService(repository, other_access),
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
