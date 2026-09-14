"""Immutable release publication retains claim arbitration through the complete workflow."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

import asyncpg
import pytest

from huron.core.access import AccessPolicy
from huron.core.idempotency import request_sha256
from huron.core.releases import Releases
from huron.pkg.auth import Principal
from huron.pkg.catalog.errors import IdempotencyKeyReused, TagExists
from huron.pkg.catalog.paths import release_tag_file
from huron.pkg.catalog.persistence import IdempotencyClaim
from huron.pkg.metastore import InMemoryRbacStore, PostgresHierarchyStore
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Classification, RoleBindingAuthorizer, ScopeType, Visibility
from tests.hierarchy_contract import _dataset, _organization, _project, committed_revision

pytestmark = pytest.mark.integration


def _claim(key: str, tag: str, title: str | None) -> IdempotencyClaim:
    """Bind a scientist's retry identity to the concrete release request's tag and title."""
    return IdempotencyClaim(
        principal="scientist", key=key, request_sha256=request_sha256("release", tag, title)
    )


async def _workspace(pool: asyncpg.Pool, root: Path):
    """Seed a committed dataset revision and bind the real release workflow over it."""
    store = PostgresHierarchyStore(pool)
    storage = PosixRawStore(str(root))
    storage.initialize()
    organization = _organization(slug=f"parent-{uuid4().hex}")
    project = _project(organization_id=organization.id, slug="parent-project")
    dataset = _dataset(project_id=project.id, slug="parent-dataset")
    revision = committed_revision(dataset.id, 1)
    async with store.transaction() as writer:
        await writer.insert_organization(organization)
        await writer.insert_project(project)
        await writer.insert_dataset(dataset, data_classification="open")
        await writer.insert_revision(revision)
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
    releases = Releases(access, store, storage)
    return store, storage, releases, organization, project, dataset


def test_concurrent_release_creation_replays_one_identity_and_refuses_conflicting_claims(
    catalog_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent complete release workflows share one claimed tag and refuse conflicting claims."""
    asyncio.run(_compete(catalog_database, tmp_path, monkeypatch))


async def _compete(dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        store, storage, releases, organization, project, dataset = await _workspace(pool, root)
        dataset_id = dataset.id
        tag_path = release_tag_file(
            PurePosixPath(storage.root), organization, project, dataset, "v1"
        )
        key = uuid4().hex
        claim = _claim(key, "v1", "original")
        barrier = asyncio.Barrier(2)
        transaction = store.transaction

        @asynccontextmanager
        async def synchronized_transaction():
            async with transaction() as writer:
                original_claim = writer.claim

                async def synchronized_claim(submission: IdempotencyClaim):
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                    return await original_claim(submission)

                with monkeypatch.context() as patch:
                    patch.setattr(writer, "claim", synchronized_claim)
                    yield writer

        ran_on_the_event_loop: list[bool] = []
        writes: list[tuple[PurePosixPath, bytes]] = []
        write_tag_once = storage.write_tag_once

        def tracked_write(tag_file: PurePosixPath, payload: bytes) -> None:
            try:
                asyncio.get_running_loop()
                ran_on_the_event_loop.append(True)
            except RuntimeError:
                ran_on_the_event_loop.append(False)
            writes.append((tag_file, payload))
            write_tag_once(tag_file, payload)

        with monkeypatch.context() as patch:
            patch.setattr(store, "transaction", synchronized_transaction)
            patch.setattr(storage, "write_tag_once", tracked_write)
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    releases.create_release(
                        dataset_id, tag="v1", revision_number=1, title="original", claim=claim
                    ),
                    releases.create_release(
                        dataset_id, tag="v1", revision_number=1, title="original", claim=claim
                    ),
                ),
                timeout=30,
            )

        assert first == second
        assert first.tag == "v1"
        assert ran_on_the_event_loop == [False]
        assert len(writes) == 1
        written_path, payload = writes[0]
        assert str(written_path) == str(tag_path)
        assert Path(str(tag_path)).read_bytes() == payload
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM releases WHERE dataset_id = $1 AND tag = $2",
                dataset_id,
                "v1",
            )
            == 1
        )
        assert await store.release(dataset_id, "v1", Visibility.ALL) == first

        with pytest.raises(IdempotencyKeyReused):
            await releases.create_release(
                dataset_id,
                tag="v1",
                revision_number=1,
                title="changed",
                claim=_claim(key, "v1", "changed"),
            )
        assert await store.release(dataset_id, "v1", Visibility.ALL) == first

        race_barrier = asyncio.Barrier(2)

        @asynccontextmanager
        async def raced_transaction():
            async with transaction() as writer:
                original_claim = writer.claim

                async def synchronized_claim(submission: IdempotencyClaim):
                    await asyncio.wait_for(race_barrier.wait(), timeout=10)
                    return await original_claim(submission)

                with monkeypatch.context() as patch:
                    patch.setattr(writer, "claim", synchronized_claim)
                    yield writer

        with monkeypatch.context() as patch:
            patch.setattr(store, "transaction", raced_transaction)
            results = await asyncio.wait_for(
                asyncio.gather(
                    releases.create_release(
                        dataset_id,
                        tag="v2",
                        revision_number=1,
                        title="race",
                        claim=_claim(uuid4().hex, "v2", "race"),
                    ),
                    releases.create_release(
                        dataset_id,
                        tag="v2",
                        revision_number=1,
                        title="race",
                        claim=_claim(uuid4().hex, "v2", "race"),
                    ),
                    return_exceptions=True,
                ),
                timeout=30,
            )

        successes = [item for item in results if not isinstance(item, BaseException)]
        failures = [item for item in results if isinstance(item, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], TagExists)
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM releases WHERE dataset_id = $1 AND tag = $2",
                dataset_id,
                "v2",
            )
            == 1
        )
    finally:
        await pool.close()
