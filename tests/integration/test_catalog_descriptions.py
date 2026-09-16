"""Authorized descriptions preserve PostgreSQL CAS and POSIX publication ordering."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path, PurePosixPath
from uuid import uuid4

import asyncpg
import pytest

from huron.core.security import AccessPolicy
from huron.core.catalog import (
    DatasetCollection,
    OrganizationCollection,
    ProjectCollection,
)
from huron.core.catalog._impl.documents import GenerationDocuments
from huron.core.catalog.types import DescriptionChange, Dataset, Organization, Project
from huron.core.security.principal import Principal
from huron.core.foundation.errors import PreconditionFailed
from huron.core.catalog.paths import dataset_dir, organization_dir, project_dir
from huron.core.metastore import InMemoryRbacStore, PostgresHierarchyStore
from huron.core.rawstore import PosixRawStore
from huron.core.security.rules import Classification, RoleBindingAuthorizer, ScopeType
from tests.hierarchy_contract import _dataset, _organization, _project

pytestmark = pytest.mark.integration


async def _workspace(pool: asyncpg.Pool, root: Path, kind: str):
    """Seed real rows and generation files, then bind an authorized typed collection."""
    store = PostgresHierarchyStore(pool)
    storage = PosixRawStore(str(root))
    storage.initialize()
    organization = _organization(slug=f"description-{uuid4().hex}")
    project = _project(organization_id=organization.id, slug="project")
    dataset = _dataset(project_id=project.id, slug="dataset")
    async with store.transaction() as writer:
        await writer.insert_organization(organization)
        await writer.insert_project(project)
        await writer.insert_dataset(dataset, data_classification=project.data_classification)
    directories = (
        organization_dir(PurePosixPath(root), organization),
        project_dir(PurePosixPath(root), organization, project),
        dataset_dir(PurePosixPath(root), organization, project, dataset),
    )
    documents = GenerationDocuments(storage)
    for directory, item in zip(directories, (organization, project, dataset), strict=True):
        await documents.write(directory, item)
    bindings = InMemoryRbacStore()
    await bindings.grant_role(
        principal="user:scientist",
        role_code="platform_owner",
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by="bootstrap",
    )
    access = AccessPolicy(
        Principal("scientist"),
        store,
        bindings,
        RoleBindingAuthorizer((Classification("open", 0, True),)),
    )
    choices = {
        "organization": (
            OrganizationCollection(access, store, storage),
            organization,
            directories[0],
        ),
        "project": (ProjectCollection(access, store, storage), project, directories[1]),
        "dataset": (DatasetCollection(access, store, storage), dataset, directories[2]),
    }
    collection, item, directory = choices[kind]
    return storage, collection, item, Path(directory)


@pytest.mark.parametrize("kind", ["organization", "project", "dataset"])
def test_concurrent_descriptions_publish_only_the_cas_winner(
    catalog_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Two matching pre-reads reach CAS; one wins and only its generation reaches disk."""
    asyncio.run(_compete(catalog_database, tmp_path, monkeypatch, kind))


async def _compete(dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        storage, collection, original, directory = await _workspace(pool, root, kind)
        barrier = asyncio.Barrier(2)
        observed_versions: list[int] = []
        get = collection.get

        async def synchronized_get(resource_id):
            item = await get(resource_id)
            observed_versions.append(item.version)
            await asyncio.wait_for(barrier.wait(), timeout=10)
            return item

        writes: list[int] = []
        loop_thread = threading.get_ident()
        write_generation = storage.write_generation

        def tracked_write(path: PurePosixPath, generation: int, document: bytes) -> None:
            assert threading.get_ident() != loop_thread
            writes.append(generation)
            write_generation(path, generation, document)

        with monkeypatch.context() as patch:
            patch.setattr(collection, "get", synchronized_get)
            patch.setattr(storage, "write_generation", tracked_write)
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    collection.describe(original.id, DescriptionChange(1, title="first")),
                    collection.describe(original.id, DescriptionChange(1, title="second")),
                    return_exceptions=True,
                ),
                timeout=30,
            )
        winners = [item for item in outcomes if isinstance(item, (Organization, Project, Dataset))]
        assert observed_versions == [1, 1]
        assert len(winners) == 1
        assert sum(isinstance(item, PreconditionFailed) for item in outcomes) == 1
        assert writes == [2]
        stored = await collection.get(original.id)
        assert stored == winners[0]
        assert stored.version == stored.generation == 2
        generations = sorted((directory / "generations").glob("*.json"))
        assert [path.name for path in generations] == ["000001.json", "000002.json"]
        assert json.loads(generations[-1].read_bytes())["title"] == stored.title
        assert json.loads((directory / "CURRENT.json").read_bytes()) == {
            "generation": 2,
            "path": "generations/000002.json",
        }
    finally:
        await pool.close()


@pytest.mark.parametrize("kind", ["organization", "project", "dataset"])
def test_description_generation_failure_rolls_back_the_database_row(
    catalog_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A real generation boundary failure leaves the row unchanged and permits a clean retry."""
    asyncio.run(_rollback(catalog_database, tmp_path, monkeypatch, kind))


async def _rollback(dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        storage, collection, original, directory = await _workspace(pool, root, kind)
        original_document = (directory / "CURRENT.json").read_bytes()
        attempted: list[int] = []

        def failed_write(_path: PurePosixPath, generation: int, _document: bytes) -> None:
            attempted.append(generation)
            raise OSError("generation storage unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(storage, "write_generation", failed_write)
            with pytest.raises(OSError, match="generation storage unavailable"):
                await collection.describe(original.id, DescriptionChange(1, title="changed"))
        assert attempted == [2]
        assert await collection.get(original.id) == original
        assert (directory / "CURRENT.json").read_bytes() == original_document
        assert [path.name for path in (directory / "generations").glob("*.json")] == ["000001.json"]
        retried = await collection.describe(original.id, DescriptionChange(1, title="changed"))
        assert retried.version == retried.generation == 2
        assert await collection.get(original.id) == retried
        assert json.loads((directory / "CURRENT.json").read_bytes())["generation"] == 2
        assert (
            json.loads((directory / "generations" / "000002.json").read_bytes())["title"]
            == "changed"
        )
    finally:
        await pool.close()
