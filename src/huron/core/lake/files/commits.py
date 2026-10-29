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
from huron.core.lake.lookups import cursor_value, find_collection, page_of
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import Conflict
from huron.pkg.identifiers import new_id, parse_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.loader import load_document
from huron.schema.naming import RelPathError, check_rel_path, rel_path_key
from huron.schema.validator import Validator, problems_context

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.collections.models import Collection
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["MAX_COMMIT_ENTRIES", "Commits", "parse_commit_request"]

MAX_COMMIT_ENTRIES = 10_000


def parse_commit_request(body: Any) -> CommitRequest:
    """Validate a commit body against ``commit-request-v1`` and the path rules."""
    if isinstance(body, dict):
        entries = len(body.get("adds") or []) + len(body.get("removes") or [])
        if entries > MAX_COMMIT_ENTRIES:
            raise CommitTooLarge(
                f"a commit holds at most {MAX_COMMIT_ENTRIES} entries",
                {"entries": entries, "maximum": MAX_COMMIT_ENTRIES},
            )
    problems = _VALIDATOR.validate(body)
    if problems:
        raise CommitInvalid("commit request is malformed", problems_context(problems))
    adds = tuple(FileAdd(a["rel_path"], a["size"], a["sha256"]) for a in body["adds"])
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
    """Applies commits and lists recorded files and commits."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def commit(
        self, actor: Actor, collection_id: uuid.UUID, request: CommitRequest
    ) -> CommitResult:
        """Apply ``request`` whole or refuse it whole."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=collection_id, lock=True
            )
            await authz.require(actor, Privilege.COLLECTION_WRITE_FILES, Scope.catalog(catalog.id))
            if not collection.settled:
                raise Conflict(
                    "files can only be committed to active or incomplete collections",
                    {"state": str(collection.state), "allowed": ["active", "incomplete"]},
                )
            remove_keys = [rel_path_key(path) for path in request.removes]
            recorded = await tx.files.existing(collection.id, remove_keys)
            missing = [
                p for p, k in zip(request.removes, remove_keys, strict=True) if k not in recorded
            ]
            if missing:
                raise FileNotRecorded("removed files are not recorded", {"rel_paths": missing[:20]})
            if request.base_version != collection.version:
                raise BaseVersionConflict(collection.version, request.base_version)
            await _check_tree(tx, collection.id, request, set(remove_keys))
            return await self._apply(tx, actor, collection, request, remove_keys)

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
        request: CommitRequest,
        remove_keys: list[str],
    ) -> CommitResult:
        now = self._clock.now()
        commit_id = new_id()
        records = [
            FileRecord(
                collection_id=collection.id,
                rel_path=add.rel_path,
                rel_path_key=rel_path_key(add.rel_path),
                size=add.size,
                sha256=add.sha256,
                recorded_at=now,
                recorded_by=actor.subject,
                commit_id=commit_id,
            )
            for add in request.adds
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
        await tx.files.delete_many(collection.id, remove_keys)
        await tx.files.upsert_many(records)
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
        return CommitResult(updated.version, file_count, commit_id)


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
            f"{path!r} is a directory holding the recorded file {child!r}",
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


_VALIDATOR = Validator(load_document("commit-request-v1"))
