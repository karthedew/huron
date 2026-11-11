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
from huron.core.lake.publications.models import (
    CommitEntry,
    CommitOutcome,
    CommitState,
    EntryAction,
    Refusal,
)
from huron.core.lake.schemas.models import SchemaEntry
from huron.core.lake.transaction import UnitOfWork
from huron.core.lake.uploads.models import (
    AttemptState,
    Failure,
    ObjectState,
    StoredObject,
    UploadAttempt,
)
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


async def stored_collection(uow: UnitOfWork) -> Collection:
    """Seed the tree of :func:`tree` and one active collection ``run7`` in its namespace."""
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
    return owner


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
        listed = await tx.namespaces.list_in_catalog(cat.id)
        assert [n.path for n in listed] == ["solar-wind", "solar-wind.a", "solar-wind.b"]
        assert list(await tx.namespaces.list_in_catalog(uuid.uuid4())) == []
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


def attempt(
    owner: Collection, subject: str = "dave", *, size: int = 4, minute: int = 0
) -> UploadAttempt:
    """A ``receiving`` attempt with one issued upload ID, active since ``minute``."""
    upload_id = new_id()
    at = START + timedelta(minutes=minute)
    return UploadAttempt(
        new_id(),
        subject,
        new_id(),
        owner.id,
        "a.txt",
        size,
        AttemptState.RECEIVING,
        upload_id,
        (upload_id,),
        at,
        at,
    )


def outcome(
    owner: Collection,
    subject: str = "dave",
    *,
    state: CommitState = CommitState.ACCEPTED,
    minute: int = 0,
) -> CommitOutcome:
    """A stored commit request of ``subject`` for ``owner``, created at ``minute``."""
    at = START + timedelta(minutes=minute)
    refusal = Refusal("BASE_VERSION_CONFLICT", "stale", {"current_version": 3})
    held = state in (CommitState.REJECTED, CommitState.BLOCKED)
    return CommitOutcome(
        new_id(),
        subject,
        new_id(),
        owner.id,
        "b" * 64,
        1,
        "h",
        None,
        state,
        at,
        at,
        refusal=refusal if held else None,
    )


def stored_object(upload_id: uuid.UUID, path: str | None = None) -> StoredObject:
    """The ``sealing`` object of ``upload_id``."""
    return StoredObject(
        new_id(),
        upload_id,
        path or f"helio/.huron-objects/{upload_id}",
        ObjectState.SEALING,
        START,
    )


def sealed(stored: StoredObject, inode: int = 7) -> StoredObject:
    """``stored`` once its seal measured 4 bytes."""
    return replace(
        stored,
        state=ObjectState.SEALED,
        size=4,
        sha256=SHA,
        inode=inode,
        sealed_at=START + timedelta(minutes=1),
    )


async def test_an_attempt_key_gives_one_attempt_of_one_subject(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first = attempt(owner)
    twin = replace(attempt(owner, size=9), attempt_id=first.attempt_id)
    elsewhere = replace(attempt(owner, "erin"), attempt_id=first.attempt_id)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        assert await tx.attempts.insert_or_lock(first) == first
        assert await tx.attempts.insert_or_lock(twin) == first
        assert await tx.attempts.insert_or_lock(elsewhere) == elsewhere
    async with uow.transaction() as tx:
        assert await tx.attempts.get("dave", first.attempt_id) == first
        assert await tx.attempts.get("erin", first.attempt_id) == elsewhere
        assert await tx.attempts.get("dave", new_id()) is None
        assert await tx.attempts.lock_uploads(twin.upload_ids) == {}
    reused = replace(
        attempt(owner), current_upload_id=first.current_upload_id, upload_ids=first.upload_ids
    )
    with pytest.raises(NameTaken) as taken:
        async with uow.transaction() as tx:
            await tx.attempts.insert_or_lock(reused)
    assert taken.value.context == {"name": str(reused.attempt_id)}


async def test_an_attempt_keeps_every_issued_id_in_the_order_of_issue(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first = attempt(owner)
    (oldest,) = first.upload_ids
    late, later, tied = uuid.UUID(int=2), uuid.UUID(int=3), uuid.UUID(int=1)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.attempts.insert_or_lock(first)
        await tx.attempts.issue(first.id, later, START + timedelta(minutes=1))
        await tx.attempts.issue(first.id, late, START + timedelta(minutes=2))
        await tx.attempts.issue(first.id, tied, START + timedelta(minutes=2))
        await tx.attempts.issue(new_id(), new_id(), START)
    reissued = replace(first, current_upload_id=tied, upload_ids=(oldest, later, tied, late))
    async with uow.transaction() as tx:
        assert await tx.attempts.get("dave", first.attempt_id) == reissued
        assert await tx.attempts.lock_uploads([oldest, late, new_id()]) == {
            oldest: reissued,
            late: reissued,
        }
        assert await tx.attempts.lock_uploads([]) == {}
        assert await tx.attempts.find_uploads([oldest, late, new_id()]) == {
            oldest: reissued,
            late: reissued,
        }
        assert await tx.attempts.find_uploads([]) == {}
    with pytest.raises(NameTaken) as taken:
        async with uow.transaction() as tx:
            await tx.attempts.issue(first.id, oldest, START)
    assert taken.value.context == {"name": str(oldest)}


async def test_an_attempt_update_writes_its_state_activity_request_and_failure_only(
    uow: UnitOfWork,
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first, request = attempt(owner), outcome(owner)
    active = START + timedelta(minutes=5)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commit_requests.insert_or_lock(request)
        await tx.attempts.insert_or_lock(first)
        consumed = replace(
            first, state=AttemptState.CONSUMED, active_at=active, commit_request_id=request.id
        )
        await tx.attempts.update(replace(consumed, rel_path="b.txt", size=9, created_at=active))
        await tx.attempts.update(attempt(owner))
    async with uow.transaction() as tx:
        assert await tx.attempts.get("dave", first.attempt_id) == consumed
        failure = Failure("SEAL_FAILED", "the copy is short")
        failed = replace(first, state=AttemptState.FAILED, failure=failure)
        await tx.attempts.update(failed)
        assert await tx.attempts.get("dave", first.attempt_id) == failed


async def test_an_attempt_outlives_its_collection(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner, other = collection(cat, ns, "run7"), collection(cat, ns, "run8")
    gone, kept = attempt(owner), attempt(other)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.collections.insert(other)
        await tx.attempts.insert_or_lock(gone)
        await tx.attempts.insert_or_lock(kept)
    async with uow.transaction() as tx:
        await tx.collections.delete(owner.id)
    async with uow.transaction() as tx:
        assert await tx.attempts.get("dave", gone.attempt_id) == replace(gone, collection_id=None)
        assert await tx.attempts.get("dave", kept.attempt_id) == kept


async def test_idle_attempts_and_staged_bytes(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    request = outcome(owner)
    receiving, ready = attempt(owner, size=1, minute=2), attempt(owner, size=2, minute=1)
    oldest, boundary = attempt(owner, size=4), attempt(owner, size=8, minute=10)
    sealing, late_sealing = attempt(owner, size=16, minute=3), attempt(owner, size=32, minute=10)
    states = {
        AttemptState.READY: 64,
        AttemptState.CONSUMED: 128,
        AttemptState.CANCELLED: 256,
        AttemptState.EXPIRED: 512,
        AttemptState.FAILED: 1024,
    }
    others = {state: attempt(owner, size=size) for state, size in states.items()}
    async with uow.transaction() as tx:
        assert await tx.attempts.staged_bytes() == 0
        await tx.collections.insert(owner)
        await tx.commit_requests.insert_or_lock(request)
        for row in (receiving, ready, oldest, boundary, sealing, late_sealing, *others.values()):
            await tx.attempts.insert_or_lock(row)
        await tx.attempts.update(replace(ready, state=AttemptState.READY))
        for row in (sealing, late_sealing):
            await tx.attempts.update(replace(row, state=AttemptState.SEALING))
        for state, row in others.items():
            held = request.id if state in (AttemptState.READY, AttemptState.CONSUMED) else None
            failure = Failure("SEAL_FAILED", "short") if state is AttemptState.FAILED else None
            changed = replace(row, state=state, commit_request_id=held, failure=failure)
            await tx.attempts.update(changed)
    before = START + timedelta(minutes=10)
    async with uow.transaction() as tx:
        idle = await tx.attempts.lock_idle(before, 10)
        assert [row.id for row in idle] == [oldest.id, ready.id, receiving.id, sealing.id]
        assert [row.id for row in await tx.attempts.lock_idle(before, 1)] == [oldest.id]
        assert await tx.attempts.lock_idle(START, 10) == []
        assert await tx.attempts.staged_bytes() == 1 + 2 + 4 + 8 + 16 + 32 + 64


async def test_a_seal_that_runs_again_uses_the_same_object(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first, second = attempt(owner), attempt(owner)
    made = stored_object(first.current_upload_id)
    again = stored_object(first.current_upload_id, "helio/.huron-objects/again")
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.attempts.insert_or_lock(first)
        await tx.attempts.insert_or_lock(second)
        assert await tx.objects.insert_or_lock(made) == made
        assert await tx.objects.insert_or_lock(again) == made
        await tx.objects.update(sealed(made))
        await tx.objects.update(sealed(again))
    async with uow.transaction() as tx:
        assert await tx.objects.insert_or_lock(again) == sealed(made)
        removed = replace(sealed(made), state=ObjectState.REMOVED)
        await tx.objects.update(replace(removed, path="ignored", created_at=START - timedelta(1)))
        assert await tx.objects.lock_uploads([first.current_upload_id, new_id()]) == {
            first.current_upload_id: removed
        }
        assert await tx.objects.lock_uploads([]) == {}
    with pytest.raises(NameTaken) as taken:
        async with uow.transaction() as tx:
            await tx.objects.insert_or_lock(stored_object(second.current_upload_id, made.path))
    assert taken.value.context == {"name": made.path}


async def test_objects_keep_inodes_of_the_whole_unsigned_range(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    attempts = [attempt(owner) for _ in INODES]
    objects = [stored_object(row.current_upload_id) for row in attempts]
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        for row, made, inode in zip(attempts, objects, INODES, strict=True):
            await tx.attempts.insert_or_lock(row)
            await tx.objects.insert_or_lock(made)
            await tx.objects.update(sealed(made, inode))
    async with uow.transaction() as tx:
        found = await tx.objects.lock_uploads([made.upload_id for made in objects])
        assert found == {
            made.upload_id: sealed(made, inode) for made, inode in zip(objects, INODES, strict=True)
        }


def ended(row: UploadAttempt, state: AttemptState, request: CommitOutcome) -> UploadAttempt:
    """``row`` in ``state``, with the request that consumed it or the failure that ended it."""
    held = request.id if state is AttemptState.CONSUMED else None
    failure = Failure("SEAL_FAILED", "short") if state is AttemptState.FAILED else None
    return replace(row, state=state, commit_request_id=held, failure=failure)


async def test_spent_upload_ids_are_not_current_or_of_a_final_attempt(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    request = outcome(owner)
    receiving, reissued, ready = attempt(owner), attempt(owner), attempt(owner)
    finals = {
        state: attempt(owner)
        for state in (
            AttemptState.CONSUMED,
            AttemptState.FAILED,
            AttemptState.CANCELLED,
            AttemptState.EXPIRED,
        )
    }
    current = new_id()
    async with uow.transaction() as tx:
        assert await tx.attempts.spent([]) == set()
        await tx.collections.insert(owner)
        await tx.commit_requests.insert_or_lock(request)
        for row in (receiving, reissued, ready, *finals.values()):
            await tx.attempts.insert_or_lock(row)
        await tx.attempts.issue(reissued.id, current, START + timedelta(minutes=1))
        await tx.attempts.update(replace(ready, state=AttemptState.READY))
        for state, row in finals.items():
            await tx.attempts.update(ended(row, state, request))
    asked = [
        receiving.current_upload_id,
        reissued.current_upload_id,
        current,
        ready.current_upload_id,
        new_id(),
        *(row.current_upload_id for row in finals.values()),
    ]
    async with uow.transaction() as tx:
        assert await tx.attempts.spent(asked) == {
            reissued.current_upload_id,
            *(row.current_upload_id for row in finals.values()),
        }


async def test_unreferenced_objects_are_spent_and_named_by_no_row(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    made, pending = commit(owner), outcome(owner)
    consumer, finished = (
        replace(outcome(owner, state=CommitState.SUCCEEDED), version=2, file_count=1)
        for _ in range(2)
    )
    rows = {
        name: attempt(owner)
        for name in ("published", "replaced", "ready", "held", "cancelled", "pending", "done")
    }
    rows["removed"], rows["superseded"] = attempt(owner), attempt(owner)
    objects = {name: stored_object(row.current_upload_id) for name, row in rows.items()}
    states = {
        "published": AttemptState.CONSUMED,
        "replaced": AttemptState.CONSUMED,
        "ready": AttemptState.READY,
        "held": AttemptState.READY,
        "cancelled": AttemptState.CANCELLED,
        "pending": AttemptState.EXPIRED,
        "done": AttemptState.EXPIRED,
        "removed": AttemptState.EXPIRED,
    }
    record = FileRecord(
        owner.id, "a.txt", "a.txt", 4, SHA, START, "t", made.id, 7, objects["published"].id
    )
    async with uow.transaction() as tx:
        assert await tx.objects.unreferenced(None, 10) == []
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
        for request in (consumer, pending, finished):
            await tx.commit_requests.insert_or_lock(request)
        for name, row in rows.items():
            await tx.attempts.insert_or_lock(row)
            await tx.objects.insert_or_lock(objects[name])
        for name, state in states.items():
            await tx.attempts.update(ended(rows[name], state, consumer))
        await tx.attempts.issue(rows["superseded"].id, new_id(), START + timedelta(minutes=1))
        await tx.objects.update(replace(objects["removed"], state=ObjectState.REMOVED))
        await tx.objects.update(sealed(objects["replaced"]))
        await tx.files.upsert_many([record])
        for request, name in ((pending, "pending"), (finished, "done"), (pending, "held")):
            entry = CommitEntry(
                len(name), EntryAction.ADD_FILE, f"{name}.txt", rows[name].current_upload_id
            )
            await tx.commit_requests.insert_entries(request.id, [entry])
    now = {**objects, "replaced": sealed(objects["replaced"])}
    expected = sorted(
        (now[name] for name in ("replaced", "cancelled", "done", "superseded")),
        key=lambda stored: stored.id,
    )
    async with uow.transaction() as tx:
        assert await tx.objects.unreferenced(None, 10) == expected
        assert await tx.objects.unreferenced(None, 1) == expected[:1]
        assert await tx.objects.unreferenced(expected[1].id, 10) == expected[2:]


async def test_a_request_key_gives_one_request_of_one_subject(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first = outcome(owner)
    twin = replace(outcome(owner), request_id=first.request_id, body_digest="c" * 64)
    elsewhere = replace(outcome(owner, "erin"), request_id=first.request_id)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        assert await tx.commit_requests.insert_or_lock(first) == first
        assert await tx.commit_requests.insert_or_lock(twin) == first
        assert await tx.commit_requests.insert_or_lock(elsewhere) == elsewhere
    async with uow.transaction() as tx:
        assert await tx.commit_requests.get("dave", first.request_id) == first
        assert await tx.commit_requests.get("erin", first.request_id) == elsewhere
        assert await tx.commit_requests.get("dave", new_id()) is None
        assert await tx.commit_requests.lock(first.id) == first
        assert await tx.commit_requests.lock(twin.id) is None
        assert await tx.commit_requests.find(first.id) == first
        assert await tx.commit_requests.find(twin.id) is None
    clash = replace(first, request_id=new_id())
    with pytest.raises(NameTaken) as taken:
        async with uow.transaction() as tx:
            await tx.commit_requests.insert_or_lock(clash)
    assert taken.value.context == {"name": str(clash.request_id)}


async def test_a_request_update_writes_its_state_result_refusal_and_time_only(
    uow: UnitOfWork,
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    first, made = outcome(owner), commit(owner)
    later = START + timedelta(minutes=3)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
        await tx.commit_requests.insert_or_lock(first)
        refusal = Refusal("FILE_BLOCKED", "a foreign file", {"rel_paths": ["a/b"], "n": 2**53 + 1})
        blocked = replace(first, state=CommitState.BLOCKED, refusal=refusal, updated_at=later)
        await tx.commit_requests.update(replace(blocked, host="ignored", base_version=7))
        assert await tx.commit_requests.lock(first.id) == blocked
        succeeded = replace(
            first,
            state=CommitState.SUCCEEDED,
            version=2,
            file_count=0,
            commit_id=made.id,
            updated_at=later,
        )
        await tx.commit_requests.update(succeeded)
        await tx.commit_requests.update(outcome(owner))
    async with uow.transaction() as tx:
        assert await tx.commit_requests.get("dave", first.request_id) == succeeded
        assert await tx.commit_requests.pending() == []
    async with uow.transaction() as tx:
        await tx.collections.delete(owner.id)
    async with uow.transaction() as tx:
        orphan = replace(succeeded, collection_id=None, commit_id=None)
        assert await tx.commit_requests.get("dave", first.request_id) == orphan


async def test_pending_requests_are_the_accepted_and_blocked_ones_oldest_first(
    uow: UnitOfWork,
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    blocked = outcome(owner, state=CommitState.BLOCKED, minute=1)
    accepted, tied = outcome(owner, minute=2), outcome(owner, minute=2)
    ended = [
        outcome(owner, state=state)
        for state in (CommitState.REJECTED, CommitState.SUCCEEDED, CommitState.ABANDONED)
    ]
    ended[1] = replace(ended[1], version=2, file_count=1)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        assert await tx.commit_requests.pending() == []
        for row in (tied, accepted, blocked, *ended):
            await tx.commit_requests.insert_or_lock(row)
    async with uow.transaction() as tx:
        assert await tx.commit_requests.pending() == [blocked, accepted, tied]


async def test_request_entries_keep_their_order_and_their_first_done_time(
    uow: UnitOfWork,
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    request, upload = outcome(owner), attempt(owner)
    entries = [
        CommitEntry(2, EntryAction.ADD_FILE, "d/a.txt", upload.current_upload_id),
        CommitEntry(0, EntryAction.REMOVE_FILE, "A.txt"),
        CommitEntry(1, EntryAction.MAKE_DIRECTORY, "d"),
    ]
    done, later = START + timedelta(minutes=1), START + timedelta(minutes=2)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.attempts.insert_or_lock(upload)
        await tx.commit_requests.insert_or_lock(request)
        await tx.commit_requests.insert_entries(request.id, entries)
        await tx.commit_requests.insert_entries(request.id, [])
        assert await tx.commit_requests.entries(new_id()) == []
    async with uow.transaction() as tx:
        await tx.commit_requests.mark_done(request.id, 1, done)
        await tx.commit_requests.mark_done(request.id, 1, later)
        await tx.commit_requests.mark_done(request.id, 9, later)
    async with uow.transaction() as tx:
        assert await tx.commit_requests.entries(request.id) == [
            entries[1],
            replace(entries[2], done_at=done),
            entries[0],
        ]
    for duplicate in (
        [CommitEntry(1, EntryAction.PRUNE_DIRECTORY, "e")],
        [CommitEntry(5, EntryAction.PRUNE_DIRECTORY, "e")] * 2,
    ):
        with pytest.raises(NameTaken) as taken:
            async with uow.transaction() as tx:
                await tx.commit_requests.insert_entries(request.id, duplicate)
        assert taken.value.context == {"name": str(request.id)}


async def test_a_collection_names_the_request_that_holds_it(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    request = outcome(owner)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commit_requests.insert_or_lock(request)
        await tx.collections.update(replace(owner, pending_request_id=request.id))
    async with uow.transaction() as tx:
        assert await tx.collections.lock(owner.id) == replace(owner, pending_request_id=request.id)
        await tx.collections.update(owner)
    async with uow.transaction() as tx:
        assert await tx.collections.get(owner.id) == owner


async def test_files_name_the_sealed_objects_that_hold_them(uow: UnitOfWork) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    made = commit(owner)
    first, second = attempt(owner), attempt(owner)
    objects = [stored_object(first.current_upload_id), stored_object(second.current_upload_id)]
    record = FileRecord(
        owner.id, "a.txt", "a.txt", 4, SHA, START, "t", made.id, 7, object_id=objects[0].id
    )
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
        for row, stored in zip((first, second), objects, strict=True):
            await tx.attempts.insert_or_lock(row)
            await tx.objects.insert_or_lock(stored)
        await tx.files.upsert_many([record])
    async with uow.transaction() as tx:
        assert await tx.files.get_many(owner.id, ["a.txt"]) == [record]
        replaced = replace(record, object_id=objects[1].id)
        await tx.files.upsert_many([replaced])
        assert await tx.files.list(owner.id, None, 10) == [replaced]


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
