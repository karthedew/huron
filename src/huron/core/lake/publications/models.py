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

    from huron.core.lake.uploads.models import StoredObject
    from huron.pkg.errors import HuronError

__all__ = [
    "MAX_BASE_VERSION",
    "MAX_ENTRIES",
    "CommitAdd",
    "CommitDraft",
    "CommitEntry",
    "CommitOutcome",
    "CommitPreview",
    "CommitRequest",
    "CommitState",
    "DraftAdd",
    "EntryAction",
    "EntryTarget",
    "Refusal",
    "Resolution",
]

MAX_ENTRIES = 10_000
"""The most adds and removes that one commit request can hold together."""

MAX_BASE_VERSION = 2**31 - 1
"""The largest version that a collection can have: the largest value of its version column."""


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


class Resolution(StrEnum):
    """What a platform administrator does with a blocked request.

    ``retry`` runs the entries that are not done again. ``abandon`` ends a request of which no
    entry is done, frees its collection and returns its uploads to ``ready``.
    """

    RETRY = "retry"
    ABANDON = "abandon"


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
    characters. No two adds name one upload. ``base_version`` is from 0 to
    :data:`MAX_BASE_VERSION`. A request that breaks a rule cannot be made.
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
        _check_base_version(self.base_version)
        for add in self.adds:
            _check_add(add)
        _check_paths([add.rel_path for add in self.adds], list(self.removes))
        _check_uploads(self.adds)

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
class DraftAdd:
    """A file that a dry run of a commit adds: the client may not know its sha256 and upload."""

    rel_path: str
    size: int
    sha256: str | None = None
    upload_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CommitDraft:
    """The body of a dry run of a commit to one collection.

    The rules of :class:`CommitRequest` hold, except that an add can leave out its ``sha256``
    and its ``upload_id``: a client asks before it uploads, so it knows neither. A sha256 that
    is present must be 64 lowercase hexadecimal characters.
    """

    collection_id: uuid.UUID
    base_version: int
    adds: tuple[DraftAdd, ...]
    removes: tuple[str, ...]

    def __post_init__(self) -> None:
        _check_entry_count(len(self.adds) + len(self.removes))
        _check_base_version(self.base_version)
        for add in self.adds:
            _check_add(add)
        _check_paths([add.rel_path for add in self.adds], list(self.removes))
        _check_uploads(tuple(add for add in self.adds if add.upload_id is not None))


@dataclass(frozen=True, slots=True)
class CommitPreview:
    """What a commit would make: the ``version`` and the ``file_count`` of the collection."""

    version: int
    file_count: int

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {"version": self.version, "file_count": self.file_count}


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
class EntryTarget:
    """An entry that is not done, with the facts that its filesystem step needs.

    ``path`` is the path of the entry in the API's form: the directory of the collection, then
    the ``rel_path`` of the entry. ``old_inode`` is the inode of the recorded file at exactly
    that path before the request, ``None`` when no file is recorded there or Huron never learned
    its inode. ``source`` is the sealed object that an ``add_file`` entry links, ``None`` for the
    other actions.
    """

    entry: CommitEntry
    path: str
    old_inode: int | None = None
    source: StoredObject | None = None


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


def _check_base_version(base_version: int) -> None:
    if not 0 <= base_version <= MAX_BASE_VERSION:
        raise CommitInvalid(
            f"the base_version must be from 0 to {MAX_BASE_VERSION}",
            {"base_version": base_version, "maximum": MAX_BASE_VERSION},
        )


def _check_add(add: CommitAdd | DraftAdd) -> None:
    if add.size < 0:
        raise CommitInvalid(
            f"the size of {add.rel_path!r} must be 0 or more",
            {"rel_path": add.rel_path, "size": add.size},
        )
    if add.sha256 is None:
        return
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


def _check_uploads(adds: tuple[CommitAdd | DraftAdd, ...]) -> None:
    named: dict[uuid.UUID | None, str] = {}
    for add in adds:
        if add.upload_id in named:
            raise CommitInvalid(
                "two adds name one upload",
                {
                    "rel_path": add.rel_path,
                    "other": named[add.upload_id],
                    "upload_id": str(add.upload_id),
                },
            )
        named[add.upload_id] = add.rel_path
