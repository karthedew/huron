"""Commits: record added and removed files in one synchronous transaction."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.files.errors import (
    BaseVersionConflict,
    CommitInvalid,
    CommitTooLarge,
    FileNotRecorded,
)
from huron.core.lake.files.models import Commit, CommitRequest, CommitResult, FileAdd, FileRecord
from huron.core.lake.lookups import (
    collection_path,
    cursor_value,
    find_collection,
    page_of,
    require_file_writer,
)
from huron.core.lake.uploads.errors import UploadReceiptMissing
from huron.core.lake.uploads.models import ReceiptMode, Removal
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.identifiers import new_id, parse_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.loader import load_document
from huron.schema.naming import RelPathError, check_rel_path, rel_path_key
from huron.schema.validator import Validator, problems_context

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime, timedelta

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.lake.uploads.models import Upload
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["MAX_COMMIT_ENTRIES", "Commits", "parse_commit_request"]

MAX_COMMIT_ENTRIES = 10_000


def parse_commit_request(body: Any, *, dry_run: bool = False) -> CommitRequest:
    """Validate a commit body against ``commit-request-v1`` and the path rules.

    A ``dry_run`` body is checked the same way except that its adds may leave out ``sha256``:
    the CLI asks before it uploads, and a file's hash is only known once it is uploaded.
    """
    if isinstance(body, dict):
        entries = len(body.get("adds") or []) + len(body.get("removes") or [])
        if entries > MAX_COMMIT_ENTRIES:
            raise CommitTooLarge(
                f"a commit can have at most {MAX_COMMIT_ENTRIES} entries",
                {"entries": entries, "maximum": MAX_COMMIT_ENTRIES},
            )
    problems = (_DRY_RUN_VALIDATOR if dry_run else _VALIDATOR).validate(body)
    if problems:
        raise CommitInvalid("the commit request is not valid", problems_context(problems))
    adds = tuple(FileAdd(a["rel_path"], a["size"], a.get("sha256")) for a in body["adds"])
    removes = tuple(body["removes"])
    _check_paths([add.rel_path for add in adds], list(removes))
    return CommitRequest(
        base_version=body["base_version"],
        adds=adds,
        removes=removes,
        host=body["host"],
        message=body.get("message"),
    )


class Commits:
    """Applies commits and lists recorded files and commits.

    With ``receipts`` required, every add must be proved by the latest placement of its path:
    a placed upload of the committer to exactly that path, with the same size and hash, placed
    less than ``upload_ttl`` ago, that no later placement by anyone replaced on disk. Optional
    receipts let an add without one through, but a proving receipt is still consumed.

    Consuming a receipt marks it committed. Older placed uploads of the same path stay as they
    are: they are no longer the latest placement, so they prove nothing and expire.
    """

    def __init__(
        self, uow: UnitOfWork, clock: Clock, receipts: ReceiptMode, upload_ttl: timedelta
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._receipts = receipts
        self._upload_ttl = upload_ttl

    async def commit(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        request: CommitRequest,
        *,
        dry_run: bool = False,
    ) -> CommitResult:
        """Apply ``request`` whole or refuse it whole.

        With ``dry_run`` every check of a real commit runs (the caller's right, the collection's
        state, the removed files, the base version and the file tree) and the answer is the
        version and file count the commit would make, but nothing is written or audited: the CLI
        learns a push will be refused before it uploads any byte. A dry run checks no receipt.

        A real commit consumes the receipts of its adds and records each receipt's inode with
        its file. It cancels the queued removals of the paths it adds again, and it queues the
        removal of each removed file, claimed for the caller, in the result's ``removals``.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=collection_id, lock=True
            )
            await require_file_writer(authz, actor, collection, catalog, "commit")
            remove_keys = [rel_path_key(path) for path in request.removes]
            recorded = {
                record.rel_path_key: record
                for record in await tx.files.get_many(collection.id, remove_keys)
            }
            missing = [
                p for p, k in zip(request.removes, remove_keys, strict=True) if k not in recorded
            ]
            if missing:
                raise FileNotRecorded(
                    "the commit removes files that are not recorded", {"rel_paths": missing[:20]}
                )
            if request.base_version != collection.version:
                raise BaseVersionConflict(collection.version, request.base_version)
            await _check_tree(tx, collection.id, request, set(remove_keys))
            if dry_run:
                return await _preview(tx, collection, request, remove_keys)
            return await self._apply(
                tx, actor, collection, catalog, request, list(recorded.values())
            )

    async def list_files(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[FileRecord]:
        """Recorded files sorted by their case-folded path."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            collection = await self._readable(tx, actor, collection_id)
            rows = await tx.files.list(
                collection.id, None if after is None else str(after), size + 1
            )
        return page_of(rows, size, lambda record: record.rel_path_key)

    async def list_commits(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[Commit]:
        """Commits newest first."""
        size = clamp_limit(limit)
        before = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            collection = await self._readable(tx, actor, collection_id)
            rows = await tx.commits.list(
                collection.id, None if before is None else parse_id(str(before)), size + 1
            )
        return page_of(rows, size, lambda commit: str(commit.id))

    async def _readable(
        self, tx: Transaction, actor: Actor, collection_id: uuid.UUID
    ) -> Collection:
        authz = Authorizer(tx.grants)
        collection, catalog = await find_collection(tx, authz, actor, collection_id=collection_id)
        await authz.require(actor, Privilege.COLLECTION_READ, Scope.catalog(catalog.id))
        return collection

    async def _apply(
        self,
        tx: Transaction,
        actor: Actor,
        collection: Collection,
        catalog: Catalog,
        request: CommitRequest,
        removed: Sequence[FileRecord],
    ) -> CommitResult:
        now = self._clock.now()
        commit_id = new_id()
        hashes = [_hash_of(add) for add in request.adds]
        receipts = await self._proving_receipts(tx, actor, collection.id, request.adds, now)
        records = [
            FileRecord(
                collection_id=collection.id,
                rel_path=add.rel_path,
                rel_path_key=rel_path_key(add.rel_path),
                size=add.size,
                sha256=sha256,
                recorded_at=now,
                recorded_by=actor.subject,
                commit_id=commit_id,
                inode=receipts[add.rel_path].inode if add.rel_path in receipts else None,
            )
            for add, sha256 in zip(request.adds, hashes, strict=True)
        ]
        new_version = collection.version + 1
        await tx.commits.insert(
            Commit(
                id=commit_id,
                collection_id=collection.id,
                base_version=request.base_version,
                new_version=new_version,
                adds=len(request.adds),
                removes=len(request.removes),
                host=request.host,
                message=request.message,
                actor=actor.subject,
                created_at=now,
            )
        )
        await tx.files.delete_many(collection.id, [record.rel_path_key for record in removed])
        await tx.files.upsert_many(records)
        await tx.uploads.mark_committed([upload.id for upload in receipts.values()], commit_id)
        removals = await _queue_removals(tx, collection, catalog, records, removed, commit_id, now)
        file_count = await tx.files.count(collection.id)
        updated = replace(collection, version=new_version, file_count=file_count, updated_at=now)
        await tx.collections.update(updated)
        await AuditWriter(tx.audit, self._clock).record(
            actor,
            Action.COLLECTION_COMMIT,
            ObjectType.COLLECTION,
            collection.id,
            catalog_id=collection.catalog_id,
            detail={
                "adds": len(request.adds),
                "removes": len(request.removes),
                "host": request.host,
                "message": request.message,
                "version": updated.version,
            },
        )
        return CommitResult(updated.version, file_count, commit_id, removals)

    async def _proving_receipts(
        self,
        tx: Transaction,
        actor: Actor,
        collection_id: uuid.UUID,
        adds: Sequence[FileAdd],
        now: datetime,
    ) -> dict[str, Upload]:
        """The receipt that proves each add, by the add's ``rel_path``; unproved adds are absent."""
        keys = [rel_path_key(add.rel_path) for add in adds]
        latest = {
            upload.rel_path_key: upload
            for upload in await tx.uploads.latest_placements(collection_id, keys)
        }
        placed_after = now - self._upload_ttl
        proving: dict[str, Upload] = {}
        unproven: list[str] = []
        for key, add in zip(keys, adds, strict=True):
            upload = latest.get(key)
            if upload is not None and upload.proves(
                actor.subject, add.rel_path, add.size, add.sha256, placed_after
            ):
                proving[add.rel_path] = upload
            else:
                unproven.append(add.rel_path)
        if unproven and self._receipts is ReceiptMode.REQUIRED:
            raise UploadReceiptMissing(unproven[0])
        return proving


async def _preview(
    tx: Transaction, collection: Collection, request: CommitRequest, remove_keys: list[str]
) -> CommitResult:
    add_keys = [rel_path_key(add.rel_path) for add in request.adds]
    replaced = await tx.files.existing(collection.id, add_keys)
    recorded = await tx.files.count(collection.id)
    file_count = recorded - len(remove_keys) + len(add_keys) - len(replaced)
    return CommitResult(collection.version + 1, file_count, None)


async def _queue_removals(
    tx: Transaction,
    collection: Collection,
    catalog: Catalog,
    added: Sequence[FileRecord],
    removed: Sequence[FileRecord],
    commit_id: uuid.UUID,
    now: datetime,
) -> tuple[Removal, ...]:
    await tx.uploads.delete_removals(collection.id, [record.rel_path_key for record in added])
    if not removed:
        return ()
    directory = await collection_path(tx, collection, catalog)
    removals = tuple(
        Removal.of(
            collection.id,
            directory,
            record.rel_path,
            record.rel_path_key,
            record.sha256,
            commit_id=commit_id,
            inode=record.inode,
            now=now,
        )
        for record in removed
    )
    await tx.uploads.insert_removals(removals)
    return removals


def _hash_of(add: FileAdd) -> str:
    if add.sha256 is None:
        raise CommitInvalid(
            f"{add.rel_path!r} has no sha256. Only a dry run may omit the sha256",
            {"rel_path": add.rel_path},
        )
    return add.sha256


def _check_paths(adds: list[str], removes: list[str]) -> None:
    _check_each(adds, removes)
    keys = {rel_path_key(path): path for path in adds}
    for key, path in keys.items():
        for parent in _parents(key):
            if parent in keys:
                raise CommitInvalid(
                    f"{path!r} lies inside {keys[parent]!r}, which the commit adds as a file",
                    {"rel_path": path, "other": keys[parent]},
                )


async def _check_tree(
    tx: Transaction, collection_id: uuid.UUID, request: CommitRequest, removed: set[str]
) -> None:
    adds = {rel_path_key(add.rel_path): add.rel_path for add in request.adds}
    parents = {parent: key for key in adds for parent in _parents(key)}
    blocking = (await tx.files.existing(collection_id, list(parents))) - removed
    if blocking:
        parent = min(blocking)
        path = adds[parents[parent]]
        raise CommitInvalid(
            f"{path!r} lies inside {parent!r}, which is a recorded file",
            {"rel_path": path, "other": parent},
        )
    prefixes = [f"{key}/" for key in adds]
    inside = await tx.files.beneath(collection_id, prefixes, len(removed) + 1)
    if inside - removed:
        child = min(inside - removed)
        path = next(adds[key] for key in adds if child.startswith(f"{key}/"))
        raise CommitInvalid(
            f"{path!r} is a directory that contains the recorded file {child!r}",
            {"rel_path": path, "other": child},
        )


def _parents(key: str) -> list[str]:
    parts = key.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts))]


def _check_each(adds: list[str], removes: list[str]) -> None:
    seen: dict[str, str] = {}
    for path in [*adds, *removes]:
        try:
            check_rel_path(path)
        except RelPathError as error:
            raise CommitInvalid(
                f"{path!r} is not a valid path", {"rel_path": path, "rule": error.rule}
            ) from error
        key = rel_path_key(path)
        if key in seen:
            raise CommitInvalid(
                "a path appears twice in the commit", {"rel_path": path, "other": seen[key]}
            )
        seen[key] = path


def _hash_optional(document: dict[str, Any]) -> dict[str, Any]:
    items = document["properties"]["adds"]["items"]
    items["required"] = [name for name in items["required"] if name != "sha256"]
    return document


_VALIDATOR = Validator(load_document("commit-request-v1"))
_DRY_RUN_VALIDATOR = Validator(_hash_optional(load_document("commit-request-v1")))
