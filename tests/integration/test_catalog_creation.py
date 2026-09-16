"""Authorized creation retains claim arbitration and durable-before-visible publication."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path, PurePosixPath
from uuid import uuid4

import asyncpg
import pytest

from huron.core.security import AccessPolicy
from huron.core.catalog import CatalogCreation
from huron.core.catalog._impl.documents import GenerationDocuments
from huron.core.foundation.retry import request_sha256, IdempotencyClaim
from huron.core.security.principal import Principal
from huron.core.foundation.errors import IdempotencyKeyReused
from huron.core.catalog.paths import organization_dir, project_dir
from huron.core.catalog.types import Dataset
from huron.core.metastore import InMemoryRbacStore, PostgresHierarchyStore
from huron.core.rawstore import PosixRawStore
from huron.core.security.rules import Classification, RoleBindingAuthorizer, ScopeType, Visibility
from tests.hierarchy_contract import _organization, _project

pytestmark = pytest.mark.integration


def _claim(kind: str, key: str, title: str) -> IdempotencyClaim:
    """Bind an actor's retry identity to the concrete creation request's title."""
    return IdempotencyClaim(
        principal="scientist", key=key, request_sha256=request_sha256(kind, title)
    )


async def _workspace(pool: asyncpg.Pool, root: Path, kind: str):
    """Seed immutable parent rows and files, then bind the explicit creation operation."""
    store = PostgresHierarchyStore(pool)
    storage = PosixRawStore(str(root))
    storage.initialize()
    organization = _organization(slug=f"parent-{uuid4().hex}")
    project = _project(organization_id=organization.id, slug="parent-project")
    async with store.transaction() as writer:
        await writer.insert_organization(organization)
        await writer.insert_project(project)
    documents = GenerationDocuments(storage)
    await documents.write(
        organization_dir(PurePosixPath(root), organization), organization
    )
    await documents.write(
        project_dir(PurePosixPath(root), organization, project), project
    )
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
    creation = CatalogCreation(access, store, storage, classification_vocabulary=("open",))
    slug = f"created-{uuid4().hex}"
    choices = {
        "organization": (
            partial(creation.create_organization, slug=slug, description=""),
            store.organizations,
        ),
        "project": (
            partial(
                creation.create_project,
                organization.id,
                slug=slug,
                description="",
                data_classification="open",
            ),
            store.projects,
        ),
        "dataset": (
            partial(
                creation.create_dataset,
                project.id,
                slug=slug,
                description="",
                profile_name="unregistered-profile",
                profile_version="verbatim",
            ),
            store.datasets,
        ),
    }
    create, reader = choices[kind]
    return store, storage, create, reader, slug


@pytest.mark.parametrize("kind", ["organization", "project", "dataset"])
def test_concurrent_creation_replays_one_identity_and_refuses_changed_claims(
    catalog_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Concurrent complete workflows share one claimed identity and publish one document."""
    asyncio.run(_compete(catalog_database, tmp_path, monkeypatch, kind))


async def _compete(dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        store, storage, create, reader, _ = await _workspace(pool, root, kind)
        key = uuid4().hex
        claim = _claim(kind, key, "original")
        barrier = asyncio.Barrier(2)
        transaction = store.transaction
        claim_entries: list[IdempotencyClaim] = []

        @asynccontextmanager
        async def synchronized_transaction():
            async with transaction() as writer:
                original_claim = writer.claim

                async def synchronized_claim(submission: IdempotencyClaim):
                    claim_entries.append(submission)
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                    return await original_claim(submission)

                with monkeypatch.context() as patch:
                    patch.setattr(writer, "claim", synchronized_claim)
                    yield writer

        loop_thread = threading.get_ident()
        writes: list[tuple[PurePosixPath, bytes]] = []
        write_generation = storage.write_generation

        def tracked_write(path: PurePosixPath, generation: int, document: bytes) -> Path:
            assert threading.get_ident() != loop_thread
            assert generation == 1
            writes.append((path, document))
            return write_generation(path, generation, document)

        with monkeypatch.context() as patch:
            patch.setattr(store, "transaction", synchronized_transaction)
            patch.setattr(storage, "write_generation", tracked_write)
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    create(title="original", claim=claim), create(title="original", claim=claim)
                ),
                timeout=30,
            )
        assert claim_entries == [claim, claim]
        assert first == second
        assert first.version == first.generation == 1
        if isinstance(first, Dataset):
            assert (first.profile_name, first.profile_version, first.entry_layer) == (
                "unregistered-profile",
                "verbatim",
                "raw",
            )
        assert await reader.get(first.id, Visibility.ALL) == first
        assert len(writes) == 1
        directory, document = writes[0]
        assert json.loads(document)["id"] == str(first.id)
        assert (Path(directory) / "generations" / "000001.json").read_bytes() == document
        assert json.loads((Path(directory) / "CURRENT.json").read_bytes())["generation"] == 1
        response = await pool.fetchval(
            "SELECT response FROM idempotency_records WHERE principal = $1 AND key = $2",
            claim.principal,
            claim.key,
        )
        assert json.loads(response) == {"kind": kind, "id": str(first.id)}
        with pytest.raises(IdempotencyKeyReused):
            await create(title="changed", claim=_claim(kind, key, "changed"))
        assert await reader.get(first.id, Visibility.ALL) == first
        assert (Path(directory) / "generations" / "000001.json").read_bytes() == document
    finally:
        await pool.close()


@pytest.mark.parametrize("kind", ["organization", "project", "dataset"])
def test_failed_creation_generation_rolls_back_identity_and_claim(
    catalog_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """A failed document publication commits neither the row nor its idempotency receipt."""
    asyncio.run(_rollback(catalog_database, tmp_path, monkeypatch, kind))


async def _rollback(dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        _, storage, create, reader, slug = await _workspace(pool, root, kind)
        table = {"organization": "organizations", "project": "projects", "dataset": "datasets"}[
            kind
        ]
        claim = _claim(kind, uuid4().hex, "original")
        before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.json")}
        attempts: list[int] = []

        def failed_write(_path: PurePosixPath, generation: int, _document: bytes) -> None:
            attempts.append(generation)
            raise OSError("generation storage unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(storage, "write_generation", failed_write)
            with pytest.raises(OSError, match="generation storage unavailable"):
                await create(title="original", claim=claim)
        assert attempts == [1]
        assert await pool.fetchval(f"SELECT count(*) FROM {table} WHERE slug = $1", slug) == 0
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM idempotency_records WHERE principal = $1 AND key = $2",
                claim.principal,
                claim.key,
            )
            == 0
        )
        assert {
            str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.json")
        } == before
        retried = await create(title="original", claim=claim)
        assert retried.version == retried.generation == 1
        assert await reader.get(retried.id, Visibility.ALL) == retried
        assert await create(title="original", claim=claim) == retried
    finally:
        await pool.close()
