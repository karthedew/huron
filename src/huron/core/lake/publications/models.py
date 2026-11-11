"""Commit requests, the entries that publish them, and their saved outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.lake.files.errors import CommitInvalid, CommitTooLarge
from huron.pkg.canonical import document_sha256
from huron.schema.naming import RelPathError, check_rel_path, rel_path_key

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from huron.pkg.errors import HuronError

__all__ = [
    "MAX_ENTRIES",
    "CommitAdd",
    "CommitEntry",
    "CommitOutcome",
    "CommitRequest",
    "CommitState",
    "EntryAction",
    "Refusal",
]

MAX_ENTRIES = 10_000
"""The most adds and removes that one commit request can hold together."""


class CommitState(StrEnum):
    """Where a commit request is in its life.

    ``rejected`` ends a request that the server refused before it accepted it. An ``accepted``
    request holds its collection until it ``succeeded``. A ``blocked`` request waits for an
    operator, who can retry it or make it ``abandoned`` while none of its entries is done.
    """

    REJECTED = "rejected"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    ABANDONED = "abandoned"


class EntryAction(StrEnum):
    """The one filesystem change of a commit entry.

    ``remove_directory`` clears the path of an added file and fails on a directory that is not
    empty. ``prune_directory`` removes a directory that the request made empty, and keeps a
    directory that holds a file that Huron did not record. ``add_file`` links a sealed object to
    its path, and replaces the file that is there.
    """

    REMOVE_FILE = "remove_file"
    REMOVE_DIRECTORY = "remove_directory"
    PRUNE_DIRECTORY = "prune_directory"
    MAKE_DIRECTORY = "make_directory"
    ADD_FILE = "add_file"


@dataclass(frozen=True, slots=True)
class CommitAdd:
    """A file that a commit adds or replaces: the bytes of the sealed upload ``upload_id``."""

    rel_path: str
    size: int
    sha256: str
    upload_id: uuid.UUID

    def canonical(self) -> dict[str, Any]:
        """The add as a JSON document, for the digest of its request."""
        return {
            "rel_path": self.rel_path,
            "size": self.size,
            "sha256": self.sha256,
            "upload_id": str(self.upload_id),
        }


@dataclass(frozen=True, slots=True)
class CommitRequest:
    """The body of a commit to one collection.

    The client chooses ``request_id``, and the key of a request is its creator's subject and
    ``request_id``. A request holds at most :data:`MAX_ENTRIES` adds and removes together. Each
    path is a valid path in a collection, and no two paths have the same key after NFC and case
    folding. Each add has a size of 0 or more and a sha256 of 64 lowercase hexadecimal
    characters. A request that breaks a rule cannot be made.
    """

    request_id: uuid.UUID
    collection_id: uuid.UUID
    base_version: int
    adds: tuple[CommitAdd, ...]
    removes: tuple[str, ...]
    host: str
    message: str | None = None

    def __post_init__(self) -> None:
        _check_entry_count(len(self.adds) + len(self.removes))
        for add in self.adds:
            _check_add(add)
        _check_paths([add.rel_path for add in self.adds], list(self.removes))

    def digest(self) -> str:
        """The sha256 of the canonical body.

        The order of the adds and of the removes does not change the digest. Each other field,
        the spelling of a path included, does.
        """
        return document_sha256(
            {
                "request_id": str(self.request_id),
                "collection_id": str(self.collection_id),
                "base_version": self.base_version,
                "adds": [
                    add.canonical() for add in sorted(self.adds, key=lambda add: add.rel_path)
                ],
                "removes": sorted(self.removes),
                "host": self.host,
                "message": self.message,
            }
        )


@dataclass(frozen=True, slots=True)
class CommitEntry:
    """One filesystem change of an accepted request, done in the order of ``ordinal``.

    ``rel_path`` is the exact spelling of the path in the collection. ``upload_id`` names the
    upload whose sealed object an ``add_file`` entry links, and is ``None`` for the other actions.
    ``done_at`` is set when the change is done.
    """

    ordinal: int
    action: EntryAction
    rel_path: str
    upload_id: uuid.UUID | None = None
    done_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Refusal:
    """The error that ended or blocked a request, as its problem document gave it."""

    code: str
    detail: str
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, error: HuronError) -> Refusal:
        """The refusal that ``error`` describes."""
        return cls(error.code, error.message, dict(error.context))

    def as_dict(self) -> dict[str, Any]:
        """Render for the API and the ``refusal`` column."""
        return {"code": self.code, "detail": self.detail, "context": dict(self.context)}


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    """The saved state of one commit request.

    ``body_digest`` is the digest of the request body (:meth:`CommitRequest.digest`). The same
    key with the same digest gets this outcome again. ``collection_id`` is ``None`` once the
    collection is deleted. A ``succeeded`` request has its ``version``, ``file_count`` and
    ``commit_id``. A ``rejected`` request, and a ``blocked`` one, has its ``refusal``.
    """

    id: uuid.UUID
    subject: str
    request_id: uuid.UUID
    collection_id: uuid.UUID | None
    body_digest: str
    base_version: int
    host: str
    message: str | None
    state: CommitState
    created_at: datetime
    updated_at: datetime
    version: int | None = None
    file_count: int | None = None
    commit_id: uuid.UUID | None = None
    refusal: Refusal | None = None

    @property
    def pending(self) -> bool:
        """Whether the request still holds its collection: ``accepted`` or ``blocked``."""
        return self.state in (CommitState.ACCEPTED, CommitState.BLOCKED)

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "request_id": str(self.request_id),
            "state": str(self.state),
            "collection_id": None if self.collection_id is None else str(self.collection_id),
            "version": self.version,
            "file_count": self.file_count,
            "commit_id": None if self.commit_id is None else str(self.commit_id),
            "refusal": None if self.refusal is None else self.refusal.as_dict(),
        }


_SHA256_LENGTH = 64
_HEX = frozenset("0123456789abcdef")


def _check_entry_count(entries: int) -> None:
    if entries > MAX_ENTRIES:
        raise CommitTooLarge(
            f"a commit can have at most {MAX_ENTRIES} entries",
            {"entries": entries, "maximum": MAX_ENTRIES},
        )


def _check_add(add: CommitAdd) -> None:
    if add.size < 0:
        raise CommitInvalid(
            f"the size of {add.rel_path!r} must be 0 or more",
            {"rel_path": add.rel_path, "size": add.size},
        )
    if len(add.sha256) != _SHA256_LENGTH or not set(add.sha256) <= _HEX:
        raise CommitInvalid(
            f"the sha256 of {add.rel_path!r} must be 64 lowercase hexadecimal characters",
            {"rel_path": add.rel_path, "sha256": add.sha256},
        )


def _check_paths(adds: list[str], removes: list[str]) -> None:
    keys: dict[str, str] = {}
    for path in [*adds, *removes]:
        try:
            check_rel_path(path)
        except RelPathError as error:
            raise CommitInvalid(
                f"{path!r} is not a valid path", {"rel_path": path, "rule": error.rule}
            ) from error
        key = rel_path_key(path)
        if key in keys:
            raise CommitInvalid(
                "a path appears twice in the commit", {"rel_path": path, "other": keys[key]}
            )
        keys[key] = path
