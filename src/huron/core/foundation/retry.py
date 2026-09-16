"""Principal-scoped retry identities, fingerprints and atomic receipt contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from uuid import UUID

_ABSENT_FIELD = "\x01"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """A principal's global retry key and exact request fingerprint."""

    principal: str
    key: str
    request_sha256: str


@dataclass(frozen=True, slots=True)
class Replay:
    """A durable receipt; unfinished ingest commits retain their reservation beyond TTL."""

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


def request_sha256(operation: str, *parts: str | None) -> str:
    """Digest an operation and its ordered fields using the persisted fingerprint encoding.

    NUL separates fields; SOH distinguishes an absent field from an empty string.

    Args:
        operation: The operation name.
        *parts: Ordered string fields, with None for absent values.

    Returns:
        The lower-case SHA-256 fingerprint.
    """
    fields = (operation, *(_ABSENT_FIELD if part is None else part for part in parts))
    return hashlib.sha256("\x00".join(fields).encode()).hexdigest()


class RetryTransaction(Protocol):
    """Claims and receipts committed atomically with the enclosing mutation."""

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Reserve a principal/key pair or return its identical prior receipt.

        Conflicting fingerprints raise IdempotencyKeyReused. Expired claims may
        be replaced except for unfinished ingest-commit reservations. Rollback
        discards the claim together with the mutation.

        Args:
            claim: The actor, global retry key and exact fingerprint.

        Returns:
            The recorded receipt, or None for a new claim.
        """
        ...

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Record the outcome within the transaction holding the claim.

        Args:
            claim: The claim acquired by this transaction.
            replay: The mutation's receipt.
        """
        ...
