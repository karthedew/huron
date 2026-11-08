"""The store contract: every adapter of the lake's ports must pass these.

Each test takes a ``uow`` fixture (a :class:`UnitOfWork` over an empty store); the modules that
import this suite provide it for the in-memory store and for PostgreSQL.
"""

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from huron.core.lake.audit.models import Action, AuditEntry, ObjectType
from huron.core.lake.catalogs.errors import CatalogNotFound
from huron.core.lake.catalogs.models import Catalog
from huron.core.lake.collections.models import Collection, Search, State
from huron.core.lake.errors import NameTaken
from huron.core.lake.files.models import Commit, FileRecord
from huron.core.lake.listing import Listed, ListOrder, Position, SortDirection, SortField
from huron.core.lake.namespaces.models import Namespace
from huron.core.lake.organizations.models import Organization
from huron.core.lake.schemas.models import SchemaEntry
from huron.core.lake.transaction import UnitOfWork
from huron.core.lake.uploads.models import Failure, Removal, Upload, UploadState
from huron.core.security.broker.keys import generate_key
from huron.core.security.rbac import PLATFORM, Role, Scope
from huron.pkg.canonical import canonical_bytes
from huron.pkg.identifiers import new_id
from tests.support.clock import START, frozen

SHA = "f" * 64
INODES = (0, 2**63 - 1, 2**63, 2**64 - 1)
"""Inodes at the edges of the unsigned 64-bit range and of the signed ``bigint`` that stores it."""


def organization(name: str = "helio") -> Organization:
    return Organization(new_id(), name, name.title(), "", 1, START, "test")


def schema(
    org: uuid.UUID | None = None,
    name: str = "huron-base",
    version: int = 1,
    extends: uuid.UUID | None = None,
) -> SchemaEntry:
    return SchemaEntry(new_id(), org, name, version, extends, {"type": "object"}, START, "test")


def catalog(org: Organization, schema_id: uuid.UUID, name: str = "heliophysics") -> Catalog:
    return Catalog(new_id(), org.id, name, name, "", schema_id, 1, START, "test")


def namespace(
    cat: Catalog, path: str, parent: Namespace | None = None, allowed: bool = True
) -> Namespace:
    return Namespace(
        new_id(),
        cat.id,
        None if parent is None else parent.id,
        path.rsplit(".", 1)[-1],
        path,
        allowed,
        1,
        START,
        "test",
    )


def collection(
    cat: Catalog,
    ns: Namespace,
    name: str,
    *,
    state: State = State.ACTIVE,
    metadata: dict[str, Any] | None = None,
) -> Collection:
    return Collection(
        id=new_id(),
        catalog_id=cat.id,
        namespace_id=ns.id,
        name=name,
        identifier=f"{cat.name}.{ns.path}.{name}",
        state=state,
        version=1,
        metadata=metadata or {"title": name},
        schema_override=None,
        file_count=0,
        created_at=START,
        created_by="test",
        updated_at=START,
    )


async def tree(uow: UnitOfWork) -> tuple[Organization, Catalog, Namespace]:
    """Seed an organization, a base schema, a catalog and one namespace."""
    org = organization()
    base = schema()
    cat = catalog(org, base.id)
    ns = namespace(cat, "solar-wind")
    async with uow.transaction() as tx:
        await tx.schemas.insert(base)
        await tx.organizations.insert(org)
        await tx.catalogs.insert(cat)
        await tx.namespaces.insert(ns)
    return org, cat, ns


async def test_a_failed_transaction_leaves_nothing_behind(uow: UnitOfWork) -> None:
    org = organization()
    with pytest.raises(RuntimeError):
        async with uow.transaction() as tx:
            await tx.organizations.insert(org)
            raise RuntimeError("boom")
    async with uow.transaction() as tx:
        assert await tx.organizations.get(org.id) is None


async def test_organizations(uow: UnitOfWork) -> None:
    a, b = organization("alpha"), organization("beta")
    async with uow.transaction() as tx:
        await tx.organizations.insert(b)
        await tx.organizations.insert(a)
    async with uow.transaction() as tx:
        assert await tx.organizations.get(a.id) == a
        assert await tx.organizations.get_by_name("beta") == b
        assert await tx.organizations.get_by_name("gamma") is None
        assert [o.name for o in await tx.organizations.list(None, None, 10)] == ["alpha", "beta"]
        assert [o.name for o in await tx.organizations.list(None, "alpha", 10)] == ["beta"]
        assert [o.name for o in await tx.organizations.list({b.id}, None, 10)] == ["beta"]
        assert await tx.organizations.list(set(), None, 10) == []
        assert [o.name for o in await tx.organizations.list(None, None, 1)] == ["alpha"]
        assert await tx.organizations.catalog_count(a.id) == 0
    with pytest.raises(NameTaken):
        async with uow.transaction() as tx:
            await tx.organizations.insert(organization("alpha"))
    changed = replace(a, name="ignored", display_name="Alpha!", description="new", version=2)
    async with uow.transaction() as tx:
        await tx.organizations.update(changed)
        await tx.organizations.update(organization("ghost"))
    async with uow.transaction() as tx:
        assert await tx.organizations.get(a.id) == replace(
            a, display_name="Alpha!", description="new", version=2
        )
        assert await tx.organizations.get_by_name("ghost") is None
    async with uow.transaction() as tx:
        await tx.organizations.delete(a.id)
        assert await tx.organizations.get(a.id) is None


async def test_the_bootstrap_lock_can_be_taken_twice_in_one_transaction(uow: UnitOfWork) -> None:
    async with uow.transaction() as tx:
        await tx.lock_bootstrap()
        await tx.lock_bootstrap()


async def test_catalogs(uow: UnitOfWork) -> None:
    org, cat, _ = await tree(uow)
    other_org = organization("geo")
    async with uow.transaction() as tx:
        await tx.organizations.insert(other_org)
        base = await tx.schemas.latest(None, "huron-base")
        assert base is not None
        geo = replace(catalog(other_org, base.id, "geophysics"), share_group="geo-readers")
        await tx.catalogs.insert(geo)
    async with uow.transaction() as tx:
        assert await tx.catalogs.get(cat.id) == cat
        assert await tx.catalogs.get_by_name("geophysics") == geo
        names = lambda rows: [c.name for c in rows]  # noqa: E731
        assert names(await tx.catalogs.list(None, None, None, 10)) == ["geophysics", "heliophysics"]
        assert names(await tx.catalogs.list(org.id, None, None, 10)) == ["heliophysics"]
        assert names(await tx.catalogs.list(None, ({other_org.id}, set()), None, 10)) == [
            "geophysics"
        ]
        assert names(await tx.catalogs.list(None, (set(), {cat.id}), None, 10)) == ["heliophysics"]
        assert names(await tx.catalogs.list(org.id, (set(), {geo.id}), None, 10)) == []
        assert names(await tx.catalogs.list(None, None, "geophysics", 10)) == ["heliophysics"]
        assert await tx.catalogs.namespace_count(cat.id) == 1
        assert await tx.organizations.catalog_count(org.id) == 1
        changed = replace(geo, version=2, description="d", share_group=None)
        await tx.catalogs.update(changed)
        assert await tx.catalogs.get(geo.id) == changed
        await tx.catalogs.update(replace(cat, share_group="helio-readers"))
        assert await tx.catalogs.get(cat.id) == replace(cat, share_group="helio-readers")
    with pytest.raises(CatalogNotFound) as missing:
        async with uow.transaction() as tx:
            await tx.catalogs.update(catalog(org, cat.schema_id, "ghost"))
    assert missing.value.context == {"catalog": "ghost"}
    with pytest.raises(NameTaken):
        async with uow.transaction() as tx:
            await tx.catalogs.insert(catalog(other_org, cat.schema_id, "heliophysics"))
    async with uow.transaction() as tx:
        await tx.catalogs.delete(geo.id)
        assert await tx.catalogs.get(geo.id) is None


async def test_namespaces(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    b = namespace(cat, "solar-wind.b", ns)
    a = namespace(cat, "solar-wind.a", ns)
    async with uow.transaction() as tx:
        await tx.namespaces.insert(b)
        await tx.namespaces.insert(a)
        await tx.collections.insert(collection(cat, ns, "run7"))
    async with uow.transaction() as tx:
        assert await tx.namespaces.get(a.id) == a
        assert await tx.namespaces.get_by_path(cat.id, "solar-wind.b") == b
        assert await tx.namespaces.get_by_path(cat.id, "nope") is None
        assert [n.name for n in await tx.namespaces.children(cat.id, ns.id, None, 10)] == ["a", "b"]
        assert [n.name for n in await tx.namespaces.children(cat.id, ns.id, "a", 10)] == ["b"]
        assert [n.name for n in await tx.namespaces.children(cat.id, None, None, 10)] == [
            "solar-wind"
        ]
        assert await tx.namespaces.child_counts(ns.id) == (2, 1)
        assert await tx.namespaces.draft_count(ns.id) == 0
        await tx.namespaces.update(replace(a, collections_allowed=False, version=2))
        assert (await tx.namespaces.get(a.id)).version == 2  # type: ignore[union-attr]
    for clash in (namespace(cat, "solar-wind.a", ns), namespace(cat, "solar-wind.run7", ns)):
        with pytest.raises(NameTaken):
            async with uow.transaction() as tx:
                await tx.namespaces.insert(clash)
    async with uow.transaction() as tx:
        await tx.namespaces.delete(b.id)
        assert await tx.namespaces.get(b.id) is None


async def test_collections(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    child = namespace(cat, "solar-wind.child", ns)
    labels = {"title": "Alpha", "description": "first", "labels": {"site": "a"}}
    alpha = collection(cat, ns, "alpha", metadata=labels)
    beta = collection(cat, ns, "beta", metadata={"title": "Beta", "nested": {"x": [1, 2]}})
    draft = collection(cat, ns, "draft", state=State.DRAFT)
    async with uow.transaction() as tx:
        await tx.namespaces.insert(child)
        for row in (beta, alpha, draft):
            await tx.collections.insert(row)
    async with uow.transaction() as tx:
        assert await tx.collections.get(beta.id) == beta
        assert await tx.collections.get_by_identifier(alpha.identifier) == alpha
        assert await tx.collections.get_by_identifier("x.y.z") is None
        locked = await tx.collections.lock(alpha.id)
        assert locked == alpha
        settled = {State.ACTIVE, State.INCOMPLETE}
        names = lambda rows: [c.name for c in rows]  # noqa: E731
        assert names(await tx.collections.list_in_namespace(ns.id, settled, None, 10)) == [
            "alpha",
            "beta",
        ]
        assert names(await tx.collections.list_in_namespace(ns.id, set(State), "alpha", 10)) == [
            "beta",
            "draft",
        ]
        assert names(await tx.collections.list_in_catalog(cat.id, {State.DRAFT})) == ["draft"]
        assert await tx.namespaces.draft_count(ns.id) == 1
        assert names(await tx.collections.search(cat.id, Search(q="ALP"), None, 10)) == ["alpha"]
        assert names(await tx.collections.search(cat.id, Search(q="first"), None, 10)) == ["alpha"]
        assert names(
            await tx.collections.search(cat.id, Search(labels=(("site", "a"),)), None, 10)
        ) == ["alpha"]
        assert (
            names(await tx.collections.search(cat.id, Search(labels=(("site", "b"),)), None, 10))
            == []
        )
        assert names(await tx.collections.search(cat.id, Search(), alpha.identifier, 10)) == [
            "beta"
        ]
        assert names(
            await tx.collections.search(cat.id, Search(states=frozenset({State.DRAFT})), None, 10)
        ) == ["draft"]
        updated = replace(
            beta,
            metadata={"title": "B"},
            schema_override={"type": "object"},
            state=State.INCOMPLETE,
            version=2,
            file_count=3,
            activated_at=START + timedelta(minutes=1),
        )
        await tx.collections.update(updated)
        assert await tx.collections.get(beta.id) == updated
    for clash in (collection(cat, ns, "alpha"), collection(cat, ns, "child")):
        with pytest.raises(NameTaken):
            async with uow.transaction() as tx:
                await tx.collections.insert(clash)
    async with uow.transaction() as tx:
        await tx.collections.delete(draft.id)
        assert await tx.collections.get(draft.id) is None


async def test_collections_keep_integers_of_any_size(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    huge = {"title": "Huge", "epoch": 2**63, "fill": -(10**31), "values": [2**53 + 1]}
    override = {"type": "object", "properties": {"epoch": {"type": "integer", "maximum": 2**64}}}
    exact = replace(collection(cat, ns, "exact", metadata=huge), schema_override=override)
    floating = collection(cat, ns, "floating", metadata={"title": "Float", "fill": -1e31})
    async with uow.transaction() as tx:
        await tx.collections.insert(exact)
        await tx.collections.insert(floating)
    async with uow.transaction() as tx:
        assert await tx.collections.get(exact.id) == exact
        found = await tx.collections.get(floating.id)
    assert found is not None
    # PostgreSQL's jsonb answers -1e31 as the integer -10000000000000000000000000000000.
    assert canonical_bytes(found.metadata) in (
        b'{"fill":-1e+31,"title":"Float"}',
        b'{"fill":-10000000000000000000000000000000,"title":"Float"}',
    )


async def test_files_and_commits(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first, second = new_id(), new_id()

    def record(path: str, size: int, commit_id: uuid.UUID) -> FileRecord:
        return FileRecord(owner.id, path, path.casefold(), size, SHA, START, "test", commit_id)

    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        for commit_id, version in ((first, 2), (second, 3)):
            await tx.commits.insert(
                Commit(commit_id, owner.id, version - 1, version, 1, 0, "h", None, "t", START)
            )
        await tx.files.upsert_many([record("B.txt", 1, first), record("a.txt", 2, first)])
        await tx.files.upsert_many([record("b.txt", 5, second)])
    async with uow.transaction() as tx:
        rows = await tx.files.list(owner.id, None, 10)
        assert [(r.rel_path, r.size) for r in rows] == [("a.txt", 2), ("b.txt", 5)]
        assert [r.rel_path for r in await tx.files.list(owner.id, "a.txt", 10)] == ["b.txt"]
        assert await tx.files.count(owner.id) == 2
        assert await tx.files.existing(owner.id, ["a.txt", "zzz"]) == {"a.txt"}
        assert await tx.files.existing(owner.id, []) == set()
        assert await tx.files.get_many(owner.id, ["b.txt", "zzz"]) == [record("b.txt", 5, second)]
        assert await tx.files.get_many(owner.id, []) == []
        assert await tx.files.beneath(owner.id, ["a", "b.t"], 10) == {"a.txt", "b.txt"}
        assert await tx.files.beneath(owner.id, ["a", "b"], 1) == {"a.txt"}
        assert await tx.files.beneath(owner.id, ["c/"], 10) == set()
        assert await tx.files.beneath(owner.id, [], 10) == set()
        await tx.files.delete_many(owner.id, ["a.txt"])
        assert await tx.files.count(owner.id) == 1
        commits = await tx.commits.list(owner.id, None, 10)
        assert [c.id for c in commits] == [second, first]
        assert [c.id for c in await tx.commits.list(owner.id, second, 10)] == [first]


async def test_files_keep_inodes_of_the_whole_unsigned_range(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    made = commit(owner)
    records = [
        FileRecord(owner.id, f"{i}.txt", f"{i}.txt", 1, SHA, START, "t", made.id, inode)
        for i, inode in enumerate((*INODES, None))
    ]
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
        await tx.files.upsert_many(records)
    async with uow.transaction() as tx:
        assert await tx.files.list(owner.id, None, 10) == records
        keys = [r.rel_path_key for r in records]
        assert sorted(await tx.files.get_many(owner.id, keys), key=lambda r: r.rel_path) == records
        swapped = [
            replace(r, inode=other.inode) for r, other in zip(records, records[::-1], strict=True)
        ]
        await tx.files.upsert_many(swapped)
        assert await tx.files.list(owner.id, None, 10) == swapped


def commit(owner: Collection) -> Commit:
    return Commit(new_id(), owner.id, 1, 2, 1, 0, "h", None, "t", START)


def upload(owner: Collection, rel_path: str, by: str = "dave") -> Upload:
    return Upload(
        new_id(), owner.id, rel_path, rel_path.casefold(), 4, UploadState.PENDING, by, START
    )


def placed(row: Upload, minute: int = 1, inode: int = 1) -> Upload:
    placed_at = START + timedelta(minutes=minute)
    return replace(row, state=UploadState.PLACED, sha256=SHA, placed_at=placed_at, inode=inode)


def removal(
    owner: Collection,
    rel_path: str,
    commit_id: uuid.UUID | None = None,
    created: int = 0,
    inode: int | None = None,
) -> Removal:
    return Removal(
        new_id(),
        owner.id,
        f"helio/heliophysics/solar-wind/{owner.name}/{rel_path}",
        rel_path,
        rel_path.casefold(),
        SHA,
        commit_id,
        START + timedelta(seconds=created),
        inode=inode,
    )


async def test_uploads(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner, other = collection(cat, ns, "run7"), collection(cat, ns, "run8")
    early, mine, theirs = (
        upload(owner, "A.txt"),
        upload(owner, "a.txt"),
        upload(owner, "a.txt", "e"),
    )
    first, tied = upload(owner, "b.txt"), upload(owner, "B.txt", "e")
    waiting, elsewhere = upload(owner, "c"), upload(other, "a.txt")
    rows = (early, mine, theirs, first, tied, waiting, elsewhere)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.collections.insert(other)
        for row in rows:
            await tx.uploads.insert(row)
    async with uow.transaction() as tx:
        assert await tx.uploads.get(waiting.id) == waiting
        assert await tx.uploads.lock(waiting.id) == waiting
        assert await tx.uploads.get(new_id()) is None
        assert await tx.uploads.lock(new_id()) is None
        assert await tx.uploads.latest_placements(owner.id, ["a.txt"]) == []
        assert await tx.uploads.placed(owner.id) == []
        minutes = ((early, 3), (mine, 1), (theirs, 2), (first, 1), (tied, 1), (elsewhere, 4))
        for row, minute in minutes:
            await tx.uploads.update(placed(row, minute))
        failed = replace(waiting, state=UploadState.FAILED, failure=Failure("X", "no space"))
        await tx.uploads.update(failed)
        await tx.uploads.update(upload(owner, "ghost.txt"))
    async with uow.transaction() as tx:
        assert await tx.uploads.get(waiting.id) == failed
        latest = await tx.uploads.latest_placements(owner.id, ["a.txt", "b.txt", "zzz"])
        assert latest == [placed(early, 3), placed(tied, 1)]
        assert await tx.uploads.latest_placements(owner.id, []) == []
        assert [row.id for row in await tx.uploads.placed(owner.id)] == [
            early.id,
            mine.id,
            theirs.id,
            first.id,
            tied.id,
        ]
        assert await tx.uploads.placed(other.id) == [placed(elsewhere, 4)]
        made = commit(owner)
        await tx.commits.insert(made)
        await tx.uploads.mark_committed([early.id, new_id()], made.id)
        await tx.uploads.mark_committed([], made.id)
    async with uow.transaction() as tx:
        committed = replace(placed(early, 3), state=UploadState.COMMITTED, commit_id=made.id)
        assert await tx.uploads.get(early.id) == committed
        assert await tx.uploads.latest_placements(owner.id, ["a.txt"]) == [committed]
        assert early.id not in {row.id for row in await tx.uploads.placed(owner.id)}
        await tx.uploads.update(placed(mine, 5))
        assert await tx.uploads.latest_placements(owner.id, ["a.txt"]) == [placed(mine, 5)]
        await tx.collections.delete(owner.id)
        for row in rows[:-1]:
            assert await tx.uploads.get(row.id) is None
        assert await tx.uploads.get(elsewhere.id) == placed(elsewhere, 4)


async def test_uploads_keep_inodes_of_the_whole_unsigned_range(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    made = commit(owner)
    rows = [upload(owner, f"{i}.txt") for i in range(len(INODES))]
    received = [placed(row, inode=inode) for row, inode in zip(rows, INODES, strict=True)]
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
        await tx.uploads.insert(received[0])
        for row in rows[1:]:
            await tx.uploads.insert(row)
    async with uow.transaction() as tx:
        for row in received[1:]:
            await tx.uploads.update(row)
        await tx.uploads.mark_committed([rows[-1].id], made.id)
    committed = replace(received[-1], state=UploadState.COMMITTED, commit_id=made.id)
    async with uow.transaction() as tx:
        for row in received[:-1]:
            assert await tx.uploads.get(row.id) == row
            assert await tx.uploads.lock(row.id) == row
        assert await tx.uploads.get(rows[-1].id) == committed
        assert await tx.uploads.placed(owner.id) == received[:-1]
        keys = [row.rel_path_key for row in rows]
        assert await tx.uploads.latest_placements(owner.id, keys) == [*received[:-1], committed]


async def test_removals(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner, other = collection(cat, ns, "run7"), collection(cat, ns, "run8")
    made, gone_commit = commit(owner), commit(other)
    first, second, third = (
        removal(owner, "A.txt", made.id, 0),
        removal(owner, "b", made.id, 1),
        removal(owner, "c", None, 2),
    )
    gone = removal(other, "a.txt", gone_commit.id, 3)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.collections.insert(other)
        await tx.commits.insert(made)
        await tx.commits.insert(gone_commit)
        await tx.uploads.insert_removals([third, first, second, gone])
        await tx.uploads.insert_removals([])
    async with uow.transaction() as tx:
        assert await tx.uploads.get_removal(first.id) == first
        assert await tx.uploads.get_removal(new_id()) is None
        await tx.collections.delete(other.id)
        orphan = replace(gone, collection_id=None, commit_id=None)
        assert await tx.uploads.get_removal(gone.id) == orphan
        now = START + timedelta(hours=1)
        claimed = await tx.uploads.claim_removals(now, START, 2)
        assert isinstance(claimed, list)
        assert all(type(row) is Removal for row in claimed)
        assert claimed == [replace(first, claimed_at=now), replace(second, claimed_at=now)]
        assert await tx.uploads.get_removal(first.id) == replace(first, claimed_at=now)
        rest = await tx.uploads.claim_removals(now, START, 10)
        assert rest == [replace(third, claimed_at=now), replace(orphan, claimed_at=now)]
        assert await tx.uploads.claim_removals(now, now, 10) == []
        later = now + timedelta(hours=1)
        reclaimed = await tx.uploads.claim_removals(later, later, 1)
        assert reclaimed == [replace(first, claimed_at=later)]
        await tx.uploads.delete_removals(owner.id, ["a.txt", "zzz"])
        await tx.uploads.delete_removals(other.id, ["b"])
        assert await tx.uploads.get_removal(first.id) is None
        assert await tx.uploads.get_removal(second.id) is not None
        await tx.uploads.delete_removal(second.id)
        await tx.uploads.delete_removal(second.id)
        assert await tx.uploads.get_removal(second.id) is None
        assert await tx.uploads.get_removal(third.id) is not None


async def test_removals_keep_their_claim_and_inodes_of_the_whole_unsigned_range(
    uow: UnitOfWork,
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    claimed_at = START + timedelta(minutes=1)
    rows = [
        replace(removal(owner, f"{i}.txt", None, i, inode), claimed_at=claimed_at)
        for i, inode in enumerate((*INODES, None))
    ]
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.uploads.insert_removals(rows)
    async with uow.transaction() as tx:
        for row in rows:
            assert await tx.uploads.get_removal(row.id) == row
        assert await tx.uploads.claim_removals(claimed_at, claimed_at, 10) == []
        later = claimed_at + timedelta(hours=1)
        reclaimed = await tx.uploads.claim_removals(later, later, 10)
        assert reclaimed == [replace(row, claimed_at=later) for row in rows]


async def test_schemas(uow: UnitOfWork) -> None:
    org, _, _ = await tree(uow)
    async with uow.transaction() as tx:
        base = await tx.schemas.latest(None, "huron-base")
        assert base is not None
        entries = [
            schema(org.id, "b", 1, base.id),
            schema(org.id, "b", 2, base.id),
            schema(org.id, "a", 1, base.id),
        ]
        for entry in entries:
            await tx.schemas.insert(entry)
    async with uow.transaction() as tx:
        assert await tx.schemas.get(entries[0].id) == entries[0]
        latest = await tx.schemas.latest(org.id, "b")
        assert latest is not None and latest.version == 2
        assert await tx.schemas.latest(org.id, "zzz") is None
        listed = [(e.name, e.version) for e in await tx.schemas.list(org.id, None, 10)]
        assert listed == [("a", 1), ("b", 2), ("b", 1)]
        after = [(e.name, e.version) for e in await tx.schemas.list(org.id, ("b", 2), 10)]
        assert after == [("b", 1)]
        assert [e.name for e in await tx.schemas.list(None, None, 10)] == ["huron-base"]
    with pytest.raises(NameTaken):
        async with uow.transaction() as tx:
            await tx.schemas.insert(schema(org.id, "a", 1, entries[0].id))


async def test_grants(uow: UnitOfWork) -> None:
    org, cat, _ = await tree(uow)
    org_scope, cat_scope = Scope.organization(org.id), Scope.catalog(cat.id)
    async with uow.transaction() as tx:
        added, removed = await tx.grants.replace(cat_scope, Role.READER, ["r1", "r2"], "t")
        assert (added, removed) == (["r1", "r2"], [])
        added, removed = await tx.grants.replace(cat_scope, Role.READER, ["r2", "r3"], "t")
        assert (added, removed) == (["r3"], ["r1"])
        await tx.grants.replace(org_scope, Role.ORG_ADMIN, ["admins"], "t")
        await tx.grants.replace(PLATFORM, Role.PLATFORM_ADMIN, ["platform"], "t")
    async with uow.transaction() as tx:
        roles = set(await tx.grants.roles_for_groups(["r2", "admins", "unknown"]))
        assert roles == {(cat_scope, Role.READER), (org_scope, Role.ORG_ADMIN)}
        assert await tx.grants.roles_for_groups([]) == []
        assert dict(await tx.grants.groups_for_scope(cat_scope)) == {Role.READER: ["r2", "r3"]}
        assert await tx.grants.enclosing(cat_scope) == [cat_scope, org_scope, PLATFORM]
        assert await tx.grants.enclosing(org_scope) == [org_scope, PLATFORM]
        assert await tx.grants.enclosing(PLATFORM) == [PLATFORM]
        stray = Scope.catalog(uuid.uuid4())
        assert await tx.grants.enclosing(stray) == [stray, PLATFORM]
        await tx.grants.delete_scope(cat_scope)
        assert dict(await tx.grants.groups_for_scope(cat_scope)) == {}


async def test_catalog_roles_are_granted_at_organization_scope(uow: UnitOfWork) -> None:
    org, cat, _ = await tree(uow)
    org_scope, cat_scope = Scope.organization(org.id), Scope.catalog(cat.id)
    async with uow.transaction() as tx:
        await tx.grants.replace(org_scope, Role.ORG_ADMIN, ["admins"], "t")
        for role in (Role.CATALOG_ADMIN, Role.CONTRIBUTOR, Role.READER):
            added, _ = await tx.grants.replace(org_scope, role, [f"org-{role}", "shared"], "t")
            assert added == sorted([f"org-{role}", "shared"])
        await tx.grants.replace(cat_scope, Role.READER, ["shared"], "t")
    async with uow.transaction() as tx:
        assert dict(await tx.grants.groups_for_scope(org_scope)) == {
            Role.ORG_ADMIN: ["admins"],
            Role.CATALOG_ADMIN: ["org-catalog_admin", "shared"],
            Role.CONTRIBUTOR: ["org-contributor", "shared"],
            Role.READER: ["org-reader", "shared"],
        }
        assert set(await tx.grants.roles_for_groups(["shared"])) == {
            (org_scope, Role.CATALOG_ADMIN),
            (org_scope, Role.CONTRIBUTOR),
            (org_scope, Role.READER),
            (cat_scope, Role.READER),
        }
        added, removed = await tx.grants.replace(org_scope, Role.READER, [], "t")
        assert (added, removed) == ([], ["org-reader", "shared"])
        assert dict(await tx.grants.groups_for_scope(cat_scope)) == {Role.READER: ["shared"]}
        await tx.grants.delete_scope(org_scope)
        assert dict(await tx.grants.groups_for_scope(org_scope)) == {}


async def test_audit(uow: UnitOfWork) -> None:
    org, cat, _ = await tree(uow)
    target = uuid.uuid4()

    def entry(
        action: Action, object_id: uuid.UUID | None, catalog_id: uuid.UUID | None
    ) -> AuditEntry:
        return AuditEntry(
            START, "t", action, ObjectType.COLLECTION, object_id, catalog_id, org.id, {"n": 1}
        )

    async with uow.transaction() as tx:
        first = await tx.audit.write(entry(Action.COLLECTION_CREATE, target, cat.id))
        second = await tx.audit.write(entry(Action.COLLECTION_ACTIVATE, target, cat.id))
        await tx.audit.write(entry(Action.SIGNING_KEY_ROTATE, None, None))
        assert first.id is not None and second.id is not None and second.id > first.id
    async with uow.transaction() as tx:
        rows = await tx.audit.for_object(target, None, 10)
        assert [r.action for r in rows] == [Action.COLLECTION_ACTIVATE, Action.COLLECTION_CREATE]
        assert rows[0].detail == {"n": 1}
        assert [r.id for r in await tx.audit.for_object(target, second.id, 10)] == [first.id]
        assert len(await tx.audit.for_catalog(cat.id, None, 10)) == 2
        assert len(await tx.audit.for_catalog(cat.id, None, 1)) == 1


async def test_keys(uow: UnitOfWork) -> None:
    clock = frozen()
    old = generate_key(clock)
    clock.advance(timedelta(minutes=1))
    new = generate_key(clock)
    async with uow.transaction() as tx:
        await tx.keys.insert_key(old)
        await tx.keys.insert_key(new)
        await tx.keys.retire_key(old.kid, clock.now())
        await tx.keys.retire_key("missing", clock.now())
    async with uow.transaction() as tx:
        keys = await tx.keys.list_keys()
        assert [k.kid for k in keys] == [new.kid, old.kid]
        assert keys[1].retired_at == clock.now()
        assert keys[0].public_jwk == new.public_jwk


@pytest.mark.parametrize("field", list(SortField))
@pytest.mark.parametrize("direction", list(SortDirection))
async def test_browse_orders_all_visible_rows_before_cursor_pagination(
    uow: UnitOfWork, field: SortField, direction: SortDirection
) -> None:
    org, cat, ns = await tree(uow)
    parent = namespace(cat, "children")
    other_org = organization("other")
    names = ["alpha", "bravo", "charlie", "delta"]
    creators = ["zoe", "alice", "alice", "éclair"]
    days = [3, 1, 1, 2]
    catalogs = [
        replace(
            catalog(org, cat.schema_id, name),
            created_by=creator,
            created_at=START + timedelta(days=day),
        )
        for name, creator, day in zip(names, creators, days, strict=True)
    ]
    namespaces = [
        replace(
            namespace(cat, f"children.{name}", parent),
            created_by=creator,
            created_at=START + timedelta(days=day),
        )
        for name, creator, day in zip(names, creators, days, strict=True)
    ]
    collections = [
        replace(
            collection(cat, ns, name), created_by=creator, created_at=START + timedelta(days=day)
        )
        for name, creator, day in zip(names, creators, days, strict=True)
    ]
    foreign = catalog(other_org, cat.schema_id, "foreign")
    async with uow.transaction() as tx:
        await tx.organizations.insert(other_org)
        await tx.catalogs.insert(foreign)
        await tx.namespaces.insert(parent)
        for c, n, item in zip(catalogs, namespaces, collections, strict=True):
            await tx.catalogs.insert(c)
            await tx.namespaces.insert(n)
            await tx.collections.insert(item)
        await tx.collections.insert(collection(cat, ns, "hidden", state=State.DRAFT))
        await tx.collections.insert(collection(cat, parent, "elsewhere"))
    expected = {
        SortField.NAME: ["alpha", "bravo", "charlie", "delta"],
        SortField.CREATED_BY: ["bravo", "charlie", "alpha", "delta"],
        SortField.CREATED_AT: ["bravo", "charlie", "delta", "alpha"],
    }[field]
    if direction is SortDirection.DESC:
        expected.reverse()
    ordering = ListOrder(field, direction)
    # One row per page forces equal primary values to cross page boundaries.
    for family in ("catalogs", "namespaces", "collections"):
        seen: list[str] = []
        rows: Sequence[Listed]
        after: Position = None
        async with uow.transaction() as tx:
            for _ in range(5):
                if family == "catalogs":
                    rows = await tx.catalogs.list(
                        org.id, ([], [c.id for c in [*catalogs, foreign]]), after, 1, ordering
                    )
                elif family == "namespaces":
                    rows = await tx.namespaces.children(cat.id, parent.id, after, 1, ordering)
                else:
                    rows = await tx.collections.list_in_namespace(
                        ns.id, {State.ACTIVE}, after, 1, ordering
                    )
                if not rows:
                    break
                seen.extend(row.name for row in rows)
                after = ordering.key(rows[-1])
        assert seen == expected, family
    async with uow.transaction() as tx:
        assert await tx.catalogs.list(org.id, ([], []), None, 20, ordering) == []
        assert await tx.namespaces.children(cat.id, namespaces[0].id, None, 20, ordering) == []
        assert await tx.collections.list_in_namespace(ns.id, set(), None, 20, ordering) == []
