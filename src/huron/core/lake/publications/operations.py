"""Commit requests: accept them, follow their entries, finalize and resolve them.

A request is published in two transactions with filesystem steps between them:

1. :meth:`Publications.submit` accepts the request: it checks the base version, the tree, the
   privilege and each upload, then saves the request, its entries and the pending request of
   the collection, and holds the uploads.
2. The API takes :meth:`Publications.next_entries`, does the filesystem step of each entry, and
   records it with :meth:`Publications.mark_done`, or :meth:`Publications.block` when the step
   finds an entry that the request does not expect.
3. :meth:`Publications.finalize` writes the file rows, the version, the count and the audit
   record, frees the collection and consumes the uploads.

No operation touches the filesystem. Every transaction takes its row locks in one order: the
collection row, the commit request row, the upload attempt rows, then the object rows.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.files.errors import BaseVersionConflict, CommitInvalid, FileNotRecorded
from huron.core.lake.files.models import Commit, FileRecord
from huron.core.lake.lookups import collection_path, find_collection, require_file_writer
from huron.core.lake.publications.errors import (
    CollectionBusy,
    CommitRequestNotFound,
    RequestIdConflict,
)
from huron.core.lake.publications.models import (
    CommitOutcome,
    CommitPreview,
    CommitState,
    EntryAction,
    EntryTarget,
    Refusal,
    Resolution,
)
from huron.core.lake.publications.planning import plan_entries
from huron.core.lake.uploads.errors import IneligibleReason, UploadIneligible, UploadNotFound
from huron.core.lake.uploads.models import AttemptState, ObjectState, file_path
from huron.core.security.rbac import PLATFORM, Authorizer, Role
from huron.pkg.errors import Conflict, Forbidden, HuronError, NotFound
from huron.pkg.identifiers import new_id
from huron.schema.naming import rel_path_key

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.publications.models import (
        CommitAdd,
        CommitDraft,
        CommitEntry,
        CommitRequest,
    )
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.lake.uploads.models import StoredObject, UploadAttempt
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Publications"]


class Publications:
    """The commit request aggregate's operations."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def submit(self, actor: Actor, request: CommitRequest) -> CommitOutcome:
        """Accept ``request`` for the actor, or save and raise its refusal.

        A request with the key (the actor's subject and ``request_id``) of a saved request gets
        the saved outcome when its digest is the saved digest, and :class:`RequestIdConflict`
        when it is not. A collection that the actor cannot see is not found, and nothing is
        saved. Each other refusal is saved as ``rejected`` in a transaction that commits, then
        raised:

        - the actor lacks ``COLLECTION_WRITE_FILES``, or the collection takes no files;
        - :class:`CollectionBusy`: the collection has a pending request;
        - :class:`BaseVersionConflict`: ``base_version`` is not the version of the collection;
        - :class:`FileNotRecorded` or :class:`CommitInvalid`: the tree refuses the request;
        - :class:`UploadNotFound`: Huron did not issue an upload ID to the actor;
        - :class:`UploadIneligible`: an upload is not the current ID of its attempt, is not
          ``ready``, is held by a pending request, or is for another collection or path, or its
          size or server sha256 is not the size or the sha256 of the add.

        An accepted request holds its collection and each of its uploads until it ends.
        """
        digest = request.digest()
        async with self._uow.transaction() as tx:
            saved = await tx.commit_requests.get(actor.subject, request.request_id)
            if saved is not None:
                return _replayed(saved, digest)
            result = await self._accept(tx, actor, request, digest)
        if isinstance(result, HuronError):
            raise result
        return result

    async def preview(self, actor: Actor, draft: CommitDraft) -> CommitPreview:
        """What a commit with the body ``draft`` would make now; nothing is saved or audited.

        The checks of :meth:`submit` run, except the checks of the uploads: the privilege, the
        pending request of the collection, the base version and the tree. Each one raises its
        refusal. A collection that the actor cannot see is not found.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=draft.collection_id
            )
            recorded, _ = await _planned(tx, authz, actor, collection, catalog, draft)
        removed = {rel_path_key(path) for path in draft.removes}
        added = {rel_path_key(add.rel_path) for add in draft.adds}
        kept = {rel_path_key(path) for path in recorded} - removed - added
        return CommitPreview(collection.version + 1, len(kept) + len(added))

    async def status(self, actor: Actor, request_id: uuid.UUID) -> CommitOutcome:
        """The saved outcome of the actor's request; another actor's request is not found."""
        async with self._uow.transaction() as tx:
            saved = await tx.commit_requests.get(actor.subject, request_id)
        if saved is None:
            raise CommitRequestNotFound(request_id)
        return saved

    async def pending(self) -> list[CommitOutcome]:
        """Every ``accepted`` and ``blocked`` request, the oldest first: the work to continue."""
        async with self._uow.transaction() as tx:
            return list(await tx.commit_requests.pending())

    async def next_entries(self, outcome: CommitOutcome) -> tuple[EntryTarget, ...]:
        """The entries of the request that are not done, in their order, with their facts.

        A request that is not pending has no entries to do. When a pending request has none,
        it is ready for :meth:`finalize`.
        """
        async with self._uow.transaction() as tx:
            request = await _request(tx, outcome)
            if not request.pending:
                return ()
            open_entries = [
                entry
                for entry in await tx.commit_requests.entries(request.id)
                if entry.done_at is None
            ]
            return await _targets(tx, request, open_entries)

    async def mark_done(self, outcome: CommitOutcome, ordinal: int) -> None:
        """Record that the filesystem step of the entry ``ordinal`` is done.

        An entry that is done already keeps its time. Raises :class:`Conflict` when the request
        is not pending.
        """
        async with self._uow.transaction() as tx:
            request = await _request(tx, outcome)
            _require_pending(request)
            await tx.commit_requests.mark_done(request.id, ordinal, self._clock.now())

    async def block(self, outcome: CommitOutcome, refusal: Refusal) -> CommitOutcome:
        """Record that a filesystem step found an entry that the request does not expect.

        The request becomes ``blocked`` with ``refusal``, and keeps its collection and its
        uploads until a platform administrator resolves it. Raises :class:`Conflict` when the
        request is not pending.
        """
        async with self._uow.transaction() as tx:
            request = await _request(tx, outcome)
            _require_pending(request)
            blocked = replace(
                request, state=CommitState.BLOCKED, refusal=refusal, updated_at=self._clock.now()
            )
            await tx.commit_requests.update(blocked)
            return blocked

    async def finalize(self, outcome: CommitOutcome) -> CommitOutcome:
        """Publish the rows of a pending request whose entries are all done.

        One transaction writes the file rows with their objects, the commit, the version (one
        more than the version of the collection now), the file count and the audit record. It
        frees the collection and consumes the uploads, and the request becomes ``succeeded``.
        A request that is not pending stays as it is, so a second call changes nothing. Raises
        :class:`Conflict` when an entry is not done.
        """
        async with self._uow.transaction() as tx:
            found = await tx.commit_requests.get(outcome.subject, outcome.request_id)
            assert found is not None
            if not found.pending:
                return found
            assert found.collection_id is not None
            collection = await tx.collections.lock(found.collection_id)
            request = await _request(tx, found)
            if not request.pending:
                return request
            assert collection is not None and collection.pending_request_id == request.id
            entries = await tx.commit_requests.entries(request.id)
            _require_done(request, entries)
            return await self._publish(tx, collection, request, entries)

    async def check_operator(self, actor: Actor) -> None:
        """Refuse an actor that may not resolve a blocked request (:class:`Forbidden`).

        Only a platform administrator resolves one. :meth:`resolve` checks it too.
        """
        async with self._uow.transaction() as tx:
            await _require_platform_admin(Authorizer(tx.grants), actor)

    async def resolve(
        self, actor: Actor, collection_id: uuid.UUID, resolution: Resolution
    ) -> CommitOutcome:
        """Retry or abandon the blocked request of a collection; for a platform administrator.

        ``retry`` makes the request ``accepted`` again, so the API runs the entries that are not
        done. ``abandon`` is possible only when no entry is done: the request becomes
        ``abandoned``, the collection is free, and each upload of the request is ``ready`` again
        and held by no request. Raises :class:`Forbidden` for another actor, :class:`NotFound`
        when the collection has no pending request, and :class:`Conflict` when the request is not
        ``blocked`` or an entry of an abandoned request is done.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            await _require_platform_admin(authz, actor)
            collection, _ = await find_collection(
                tx, authz, actor, collection_id=collection_id, lock=True
            )
            request = await _blocked_request(tx, collection)
            if resolution is Resolution.RETRY:
                retried = replace(
                    request, state=CommitState.ACCEPTED, refusal=None, updated_at=self._clock.now()
                )
                await tx.commit_requests.update(retried)
                return retried
            return await self._abandon(tx, collection, request)

    async def _accept(
        self, tx: Transaction, actor: Actor, request: CommitRequest, digest: str
    ) -> CommitOutcome | HuronError:
        """The acceptance transaction; a refusal is saved and returned, to raise after commit."""
        authz = Authorizer(tx.grants)
        collection, catalog = await find_collection(
            tx, authz, actor, collection_id=request.collection_id, lock=True
        )
        candidate = self._outcome(actor, request, digest)
        saved = await tx.commit_requests.insert_or_lock(candidate)
        if saved.id != candidate.id:
            return _replayed(saved, digest)
        try:
            entries, attempts = await _acceptance(tx, authz, actor, collection, catalog, request)
        except _REFUSALS as error:
            rejected = replace(
                saved,
                state=CommitState.REJECTED,
                refusal=Refusal.of(error),
                updated_at=self._clock.now(),
            )
            await tx.commit_requests.update(rejected)
            return error
        await tx.commit_requests.insert_entries(saved.id, entries)
        await tx.collections.update(replace(collection, pending_request_id=saved.id))
        for attempt in attempts:
            await tx.attempts.update(replace(attempt, commit_request_id=saved.id))
        return saved

    def _outcome(self, actor: Actor, request: CommitRequest, digest: str) -> CommitOutcome:
        now = self._clock.now()
        return CommitOutcome(
            id=new_id(),
            subject=actor.subject,
            request_id=request.request_id,
            collection_id=request.collection_id,
            body_digest=digest,
            base_version=request.base_version,
            host=request.host,
            message=request.message,
            state=CommitState.ACCEPTED,
            created_at=now,
            updated_at=now,
        )

    async def _publish(
        self,
        tx: Transaction,
        collection: Collection,
        request: CommitOutcome,
        entries: Sequence[CommitEntry],
    ) -> CommitOutcome:
        """The final transaction of a request whose entries are all done."""
        now = self._clock.now()
        commit = new_id()
        upload_ids = [entry.upload_id for entry in entries if entry.upload_id is not None]
        attempts = await tx.attempts.lock_uploads(upload_ids)
        objects = await tx.objects.lock_uploads(upload_ids)
        records = [
            _record(collection.id, entry.rel_path, objects[entry.upload_id], request, commit, now)
            for entry in entries
            if entry.upload_id is not None
        ]
        removed = _removed_keys(entries)
        removes = len(removed - {record.rel_path_key for record in records})
        version = collection.version + 1
        await tx.commits.insert(
            Commit(
                id=commit,
                collection_id=collection.id,
                base_version=request.base_version,
                new_version=version,
                adds=len(records),
                removes=removes,
                host=request.host,
                message=request.message,
                actor=request.subject,
                created_at=now,
            )
        )
        await tx.files.delete_many(collection.id, removed)
        await tx.files.upsert_many(records)
        file_count = await tx.files.count(collection.id)
        await tx.collections.update(
            replace(
                collection,
                version=version,
                file_count=file_count,
                updated_at=now,
                pending_request_id=None,
            )
        )
        for attempt in attempts.values():
            await tx.attempts.update(replace(attempt, state=AttemptState.CONSUMED))
        await AuditWriter(tx.audit, self._clock).record(
            request.subject,
            Action.COLLECTION_COMMIT,
            ObjectType.COLLECTION,
            collection.id,
            catalog_id=collection.catalog_id,
            detail={
                "adds": len(records),
                "removes": removes,
                "host": request.host,
                "message": request.message,
                "version": version,
            },
        )
        succeeded = replace(
            request,
            state=CommitState.SUCCEEDED,
            version=version,
            file_count=file_count,
            commit_id=commit,
            refusal=None,
            updated_at=now,
        )
        await tx.commit_requests.update(succeeded)
        return succeeded

    async def _abandon(
        self, tx: Transaction, collection: Collection, request: CommitOutcome
    ) -> CommitOutcome:
        entries = await tx.commit_requests.entries(request.id)
        done = [entry.ordinal for entry in entries if entry.done_at is not None]
        if done:
            raise Conflict(
                "an entry of the commit request is done. You cannot abandon the request",
                {"request_id": str(request.request_id), "done": done[:20]},
            )
        abandoned = replace(request, state=CommitState.ABANDONED, updated_at=self._clock.now())
        await tx.commit_requests.update(abandoned)
        await tx.collections.update(replace(collection, pending_request_id=None))
        upload_ids = [entry.upload_id for entry in entries if entry.upload_id is not None]
        for attempt in (await tx.attempts.lock_uploads(upload_ids)).values():
            await tx.attempts.update(
                replace(attempt, state=AttemptState.READY, commit_request_id=None)
            )
        return abandoned


_REFUSALS = (
    Forbidden,
    Conflict,
    CollectionBusy,
    BaseVersionConflict,
    FileNotRecorded,
    CommitInvalid,
    UploadNotFound,
    UploadIneligible,
)
"""The refusals of an acceptance, which are saved. ``NameTaken`` is not one of them: on
PostgreSQL the transaction that raised it is ended."""

_PAGE = 1000
"""How many recorded paths one read of the acceptance gets."""


async def _require_platform_admin(authz: Authorizer, actor: Actor) -> None:
    if (PLATFORM, Role.PLATFORM_ADMIN) not in await authz.roles_for(actor):
        raise Forbidden(
            "this operation needs the platform_admin role",
            {"role": str(Role.PLATFORM_ADMIN), "scope": "platform"},
        )


def _replayed(saved: CommitOutcome, digest: str) -> CommitOutcome:
    """The saved outcome of a request sent again; another body is a conflict."""
    if saved.body_digest != digest:
        raise RequestIdConflict(saved.request_id)
    return saved


async def _request(tx: Transaction, outcome: CommitOutcome) -> CommitOutcome:
    """The stored request of ``outcome``, locked. A stored request is never deleted."""
    locked = await tx.commit_requests.lock(outcome.id)
    assert locked is not None
    return locked


def _require_pending(request: CommitOutcome) -> None:
    if not request.pending:
        raise Conflict(
            f"the commit request is {request.state}. It has no more entries to do",
            {
                "request_id": str(request.request_id),
                "state": str(request.state),
                "allowed": [str(CommitState.ACCEPTED), str(CommitState.BLOCKED)],
            },
        )


def _require_done(request: CommitOutcome, entries: Sequence[CommitEntry]) -> None:
    open_entries = [entry.ordinal for entry in entries if entry.done_at is None]
    if open_entries:
        raise Conflict(
            "an entry of the commit request is not done. Do each entry, then finalize the request",
            {"request_id": str(request.request_id), "open": open_entries[:20]},
        )


async def _acceptance(
    tx: Transaction,
    authz: Authorizer,
    actor: Actor,
    collection: Collection,
    catalog: Catalog,
    request: CommitRequest,
) -> tuple[tuple[CommitEntry, ...], list[UploadAttempt]]:
    """The entries of ``request`` and the attempts of its adds; raises the first refusal."""
    _, entries = await _planned(tx, authz, actor, collection, catalog, request)
    return entries, await _eligible(tx, actor, request)


async def _planned(
    tx: Transaction,
    authz: Authorizer,
    actor: Actor,
    collection: Collection,
    catalog: Catalog,
    request: CommitRequest | CommitDraft,
) -> tuple[list[str], tuple[CommitEntry, ...]]:
    """The recorded paths of the collection and the entries of ``request``.

    Runs the checks that need no upload and raises the first refusal: the privilege, the
    pending request, the base version, the tree.
    """
    await require_file_writer(authz, actor, collection, catalog, "commit")
    if collection.pending_request_id is not None:
        raise CollectionBusy(collection.id)
    if request.base_version != collection.version:
        raise BaseVersionConflict(collection.version, request.base_version)
    recorded = await _recorded_paths(tx, collection.id)
    return recorded, plan_entries(recorded, request)


async def _recorded_paths(tx: Transaction, collection_id: uuid.UUID) -> list[str]:
    """The path of every recorded file of the collection."""
    paths: list[str] = []
    after: str | None = None
    while True:
        page = await tx.files.list(collection_id, after, _PAGE)
        paths += [record.rel_path for record in page]
        if len(page) < _PAGE:
            return paths
        after = page[-1].rel_path_key


async def _eligible(tx: Transaction, actor: Actor, request: CommitRequest) -> list[UploadAttempt]:
    """The attempt of each add, locked, when each upload can be published by the add."""
    upload_ids = [add.upload_id for add in request.adds]
    attempts = await tx.attempts.lock_uploads(upload_ids)
    objects = await tx.objects.lock_uploads(upload_ids)
    for add in request.adds:
        _check_upload(add, attempts.get(add.upload_id), objects.get(add.upload_id), actor, request)
    return [attempts[upload_id] for upload_id in upload_ids]


def _check_upload(
    add: CommitAdd,
    attempt: UploadAttempt | None,
    stored: StoredObject | None,
    actor: Actor,
    request: CommitRequest,
) -> None:
    """Raise unless ``attempt`` is the actor's ready, free upload of exactly the add's file."""
    if attempt is None or attempt.subject != actor.subject:
        raise UploadNotFound(add.upload_id)
    if attempt.current_upload_id != add.upload_id:
        raise UploadIneligible.for_commit(add.upload_id, attempt.state, IneligibleReason.SUPERSEDED)
    if attempt.state is not AttemptState.READY:
        raise UploadIneligible.for_commit(add.upload_id, attempt.state)
    if attempt.commit_request_id is not None:
        raise UploadIneligible.for_commit(add.upload_id, attempt.state, IneligibleReason.HELD)
    if not _same_file(add, attempt, stored, request.collection_id):
        raise UploadIneligible.for_commit(
            add.upload_id, attempt.state, IneligibleReason.DIFFERENT_FILE
        )


def _same_file(
    add: CommitAdd,
    attempt: UploadAttempt,
    stored: StoredObject | None,
    collection_id: uuid.UUID,
) -> bool:
    """Whether the sealed object of ``attempt`` holds the file of ``add`` in the collection."""
    return (
        stored is not None
        and stored.state is ObjectState.SEALED
        and (attempt.collection_id, attempt.rel_path) == (collection_id, add.rel_path)
        and (stored.size, stored.sha256) == (add.size, add.sha256)
    )


async def _targets(
    tx: Transaction, request: CommitOutcome, entries: Sequence[CommitEntry]
) -> tuple[EntryTarget, ...]:
    """Each entry with its path, the inode of the file it replaces and its object."""
    assert request.collection_id is not None
    collection = await tx.collections.get(request.collection_id)
    assert collection is not None
    catalog = await tx.catalogs.get(collection.catalog_id)
    assert catalog is not None
    directory = await collection_path(tx, collection, catalog)
    keys = [rel_path_key(entry.rel_path) for entry in entries]
    recorded = {
        record.rel_path: record.inode for record in await tx.files.get_many(collection.id, keys)
    }
    upload_ids = [entry.upload_id for entry in entries if entry.upload_id is not None]
    objects = await tx.objects.lock_uploads(upload_ids)
    return tuple(
        EntryTarget(
            entry=entry,
            path=file_path(directory, entry.rel_path),
            old_inode=recorded.get(entry.rel_path),
            source=None if entry.upload_id is None else objects[entry.upload_id],
        )
        for entry in entries
    )


async def _blocked_request(tx: Transaction, collection: Collection) -> CommitOutcome:
    """The pending request of ``collection``, locked; it must be ``blocked``."""
    if collection.pending_request_id is None:
        raise NotFound(
            "the collection has no pending commit request", {"collection": str(collection.id)}
        )
    request = await tx.commit_requests.lock(collection.pending_request_id)
    assert request is not None
    if request.state is not CommitState.BLOCKED:
        raise Conflict(
            f"the commit request is {request.state}. You can resolve only a blocked request",
            {
                "request_id": str(request.request_id),
                "state": str(request.state),
                "allowed": [str(CommitState.BLOCKED)],
            },
        )
    return request


def _record(
    collection_id: uuid.UUID,
    rel_path: str,
    stored: StoredObject,
    request: CommitOutcome,
    commit_id: uuid.UUID,
    now: datetime,
) -> FileRecord:
    """The file row of an add: the measured size, sha256 and inode of its sealed object."""
    assert stored.size is not None and stored.sha256 is not None
    return FileRecord(
        collection_id=collection_id,
        rel_path=rel_path,
        rel_path_key=rel_path_key(rel_path),
        size=stored.size,
        sha256=stored.sha256,
        recorded_at=now,
        recorded_by=request.subject,
        commit_id=commit_id,
        inode=stored.inode,
        object_id=stored.id,
    )


def _removed_keys(entries: Sequence[CommitEntry]) -> set[str]:
    """The key of each file that a ``remove_file`` entry removes."""
    return {
        rel_path_key(entry.rel_path) for entry in entries if entry.action is EntryAction.REMOVE_FILE
    }
