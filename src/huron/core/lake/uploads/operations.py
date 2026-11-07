"""Uploads: begin, place, receive and end uploads, and drain the removal outbox.

The API calls these for tusd's hooks and for its own disk work. ``begin``, ``placement``,
``terminate`` and ``get`` act for the uploading user and are authorized for them. ``receipt``,
``fail`` and the removal operations record the API's own disk work, so they take no actor.

Every transaction takes its row locks in one order: the collection row, then upload rows, then
removal rows, as commits and collection deletes do. ``begin`` locks the collection before it
inserts the upload, so a collection delete at the same time either finds the new upload or makes
``begin`` fail with the collection's not-found error. A receipt changes which upload is the
latest placement of its path, so it locks the collection, then the upload, and serializes with
the commits that consume receipts and with the collection delete that queues the removal of every
placed file. Failing or ending an upload touches only an unplaced row, which neither reads, so
those lock the upload alone. ``placement``, ``get`` and ``removal_still_valid`` lock nothing, and
the removal claims skip the removal rows that another transaction locks.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

from huron.core.lake.lookups import collection_view, find_collection
from huron.core.lake.uploads.errors import (
    UploadNotFound,
    UploadSizeMismatch,
    UploadStateConflict,
    UploadTooLarge,
)
from huron.core.lake.uploads.models import (
    ClaimedRemoval,
    Destination,
    Failure,
    Upload,
    UploadState,
    file_path,
)
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import Conflict, Invalid
from huron.pkg.identifiers import new_id
from huron.pkg.paging import clamp_limit
from huron.schema.naming import check_rel_path, rel_path_key

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.organizations.declarations import Declarations
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["REMOVAL_LEASE", "Uploads"]

REMOVAL_LEASE = timedelta(minutes=15)
"""How long a claimed removal stays with its claimer before another claim may take it."""

_SHA256_LENGTH = 64
_HEX = frozenset("0123456789abcdef")


class Uploads:
    """The upload aggregate's operations.

    ``ttl`` is how long a receipt stays good for a commit; ``max_size`` is the largest upload
    in bytes, ``0`` for no limit.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        declarations: Declarations,
        *,
        ttl: timedelta,
        max_size: int,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._declarations = declarations
        self._ttl = ttl
        self._max_size = max_size

    async def begin(
        self, actor: Actor, collection_id: uuid.UUID, rel_path: str, size: int
    ) -> Upload:
        """Start an upload of ``size`` bytes to ``rel_path`` of a settled collection."""
        check_rel_path(rel_path)
        if size < 0:
            raise Invalid("the size must be 0 or more", {"size": size})
        if self._max_size and size > self._max_size:
            raise UploadTooLarge(size, self._max_size)
        async with self._uow.transaction() as tx:
            await _writable(tx, actor, collection_id, lock=True)
            upload = Upload(
                id=new_id(),
                collection_id=collection_id,
                rel_path=rel_path,
                rel_path_key=rel_path_key(rel_path),
                size=size,
                state=UploadState.PENDING,
                created_by=actor.subject,
                created_at=self._clock.now(),
            )
            await tx.uploads.insert(upload)
            return upload

    async def placement(self, actor: Actor, upload_id: uuid.UUID) -> Destination:
        """Where the creator's pending upload goes; its collection must still take files."""
        async with self._uow.transaction() as tx:
            upload = _owned(await tx.uploads.get(upload_id), actor, upload_id)
            _require(upload, UploadState.PENDING)
            collection, catalog = await _writable(tx, actor, upload.collection_id)
            view = await collection_view(tx, collection, catalog)
            assert view.disk_path is not None
            return Destination(
                file_path(view.disk_path, upload.rel_path),
                self._declarations.share_root(view.organization),
            )

    async def receipt(self, upload_id: uuid.UUID, size: int, sha256: str, inode: int) -> Upload:
        """Record that the upload's bytes are at their destination.

        ``size`` and ``sha256`` describe the placed bytes, and ``inode`` is the placed file's
        inode. Repeating the receipt of a placed upload with the same size and hash changes
        nothing: the upload keeps its first inode.
        """
        _check_sha256(sha256)
        async with self._uow.transaction() as tx:
            upload = await _locked_with_collection(tx, upload_id)
            if upload.state is UploadState.PLACED and (upload.size, upload.sha256) == (
                size,
                sha256,
            ):
                return upload
            _require(upload, UploadState.PENDING)
            if size != upload.size:
                raise UploadSizeMismatch(upload.size, size)
            placed = replace(
                upload,
                state=UploadState.PLACED,
                sha256=sha256,
                placed_at=self._clock.now(),
                inode=inode,
            )
            await tx.uploads.update(placed)
            return placed

    async def fail(self, upload_id: uuid.UUID, code: str, message: str) -> Upload:
        """Record why a pending upload could not be placed."""
        async with self._uow.transaction() as tx:
            upload = _found(await tx.uploads.lock(upload_id), upload_id)
            _require(upload, UploadState.PENDING)
            failed = replace(upload, state=UploadState.FAILED, failure=Failure(code, message))
            await tx.uploads.update(failed)
            return failed

    async def terminate(self, actor: Actor, upload_id: uuid.UUID) -> Upload:
        """End the creator's upload that was never placed; ending it again changes nothing."""
        async with self._uow.transaction() as tx:
            upload = _owned(await tx.uploads.lock(upload_id), actor, upload_id)
            if upload.state is UploadState.TERMINATED:
                return upload
            _require(upload, UploadState.PENDING, UploadState.FAILED)
            terminated = replace(upload, state=UploadState.TERMINATED)
            await tx.uploads.update(terminated)
            return terminated

    async def get(self, actor: Actor, upload_id: uuid.UUID) -> Upload:
        """The upload, for its creator only."""
        async with self._uow.transaction() as tx:
            return _owned(await tx.uploads.get(upload_id), actor, upload_id)

    async def claim_removals(self, limit: int | None = None) -> list[ClaimedRemoval]:
        """Claim up to ``limit`` removals, oldest first: unclaimed ones and stale claims."""
        now = self._clock.now()
        async with self._uow.transaction() as tx:
            removals = await tx.uploads.claim_removals(now, now - REMOVAL_LEASE, clamp_limit(limit))
        return [
            ClaimedRemoval(removal, self._declarations.share_root(removal.organization))
            for removal in removals
        ]

    async def removal_still_valid(self, removal_id: uuid.UUID) -> bool:
        """Whether the API may still unlink the removal's file.

        It may not when the removal is gone, or when the settled collection now at the removal's
        directory, whether the removal's own or one created there since, records a file at its
        path again or holds an upload placed there that may still be committed. Paths compare
        by their case-folded key: on a case-insensitive share two spellings are one file.
        """
        async with self._uow.transaction() as tx:
            removal = await tx.uploads.get_removal(removal_id)
            if removal is None:
                return False
            collection_id = await _collection_at(tx, removal.directory)
            if collection_id is None:
                return True
            keys = [removal.rel_path_key]
            if await tx.files.existing(collection_id, keys):
                return False
            placed_after = self._clock.now() - self._ttl
            return not any(
                upload.state is UploadState.PLACED
                and upload.placed_at is not None
                and upload.placed_at > placed_after
                for upload in await tx.uploads.latest_placements(collection_id, keys)
            )

    async def finish_removal(self, removal_id: uuid.UUID) -> None:
        """Forget a removal the API made or gave up; a finished removal stays finished."""
        async with self._uow.transaction() as tx:
            await tx.uploads.delete_removal(removal_id)


async def _locked_with_collection(tx: Transaction, upload_id: uuid.UUID) -> Upload:
    """The upload, locked after its collection.

    A collection deleted in the meantime took its uploads with it, so the upload's lock then
    finds nothing.
    """
    upload = _found(await tx.uploads.get(upload_id), upload_id)
    await tx.collections.lock(upload.collection_id)
    return _found(await tx.uploads.lock(upload_id), upload_id)


async def _collection_at(tx: Transaction, directory: str) -> uuid.UUID | None:
    """The id of the settled collection whose directory is ``directory``, if there is one."""
    _, *names = directory.split("/")
    collection = await tx.collections.get_by_identifier(".".join(names))
    if collection is None:
        return None
    catalog = await tx.catalogs.get(collection.catalog_id)
    assert catalog is not None
    view = await collection_view(tx, collection, catalog)
    return collection.id if view.disk_path == directory else None


async def _writable(
    tx: Transaction, actor: Actor, collection_id: uuid.UUID, *, lock: bool = False
) -> tuple[Collection, Catalog]:
    authz = Authorizer(tx.grants)
    collection, catalog = await find_collection(
        tx, authz, actor, collection_id=collection_id, lock=lock
    )
    await authz.require(actor, Privilege.COLLECTION_WRITE_FILES, Scope.catalog(catalog.id))
    if not collection.settled:
        raise Conflict(
            "you can upload files only to an active or incomplete collection",
            {"state": str(collection.state), "allowed": ["active", "incomplete"]},
        )
    return collection, catalog


def _found(upload: Upload | None, upload_id: uuid.UUID) -> Upload:
    if upload is None:
        raise UploadNotFound(upload_id)
    return upload


def _owned(upload: Upload | None, actor: Actor, upload_id: uuid.UUID) -> Upload:
    if upload is None or upload.created_by != actor.subject:
        raise UploadNotFound(upload_id)
    return upload


def _require(upload: Upload, *allowed: UploadState) -> None:
    if upload.state not in allowed:
        raise UploadStateConflict(upload.state, allowed)


def _check_sha256(sha256: str) -> None:
    if len(sha256) != _SHA256_LENGTH or not set(sha256) <= _HEX:
        raise Invalid("the sha256 must be 64 lowercase hexadecimal characters", {"sha256": sha256})
