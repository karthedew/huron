"""Values exchanged across persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from uuid import UUID

    from .ingest import IngestFile


class PlatformRoot(Enum):
    """The explicit parent of organizations in the catalog hierarchy."""

    ROOT = "platform"


@dataclass(frozen=True, slots=True)
class Window[ItemT]:
    """``limit`` items after a keyset position, and whether more follow.

    Attributes:
        items: At most ``limit`` items, ordered by the store's cursor key.
        has_more: Whether at least one further visible item follows the
            last one in ``items``.
    """

    items: list[ItemT]
    has_more: bool


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """One principal's bid to run a write exactly once, keyed by an ``Idempotency-Key`` header.

    Attributes:
        principal: The acting principal's subject, e.g. ``"user:alice"``.
        key: The ``Idempotency-Key`` header value the caller supplied.
        request_sha256: A hex digest over the operation name and its
            arguments, so a replayed key attached to a different request
            is distinguishable from a genuine retry.
    """

    principal: str
    key: str
    request_sha256: str


@dataclass(slots=True)
class LedgerEntry:
    """One ingest file together with the session whose ledger it belongs to.

    Attributes:
        ingest_id: The session the file was planned under.
        file: The file's progress through that session's ledger.
    """

    ingest_id: UUID
    file: IngestFile


@dataclass(frozen=True, slots=True)
class Replay:
    """What one idempotent write produced, kept so a later replay of its claim can return it.

    ``ingest_commit`` binds an unfinished publication to its ingest session, not
    to a readable revision. It remains reserved beyond the ordinary retry TTL
    until the revision transaction replaces it with a ``revision`` receipt.

    Attributes:
        kind: Which hierarchy level, or ingest step, the claimed write created.
        resource_id: The id of the resource that write created.
    """

    kind: Literal[
        "organization",
        "project",
        "dataset",
        "release",
        "ingest_session",
        "ingest_commit",
        "revision",
    ]
    resource_id: UUID
