"""Principal-scoped retry identities, fingerprints and atomic receipt contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """A principal's global retry key and exact request fingerprint."""

    principal: str
    key: str
    request_sha256: str


@dataclass(frozen=True, slots=True)
class Replay:
    """A durable receipt for an accepted hierarchy or lake administration mutation."""

    kind: Literal[
        "organization",
        "project",
        "dataset",
        "catalog",
        "metadata_schema",
        "signing_key",
    ]
    resource_id: UUID


def request_sha256(operation: str, *parts: str) -> str:
    """Digest an operation and its ordered fields using the persisted fingerprint encoding.

    The operation and its fields are joined by NUL and hashed as UTF-8.

    Args:
        operation: The operation name.
        *parts: Ordered string fields.

    Returns:
        The lower-case SHA-256 fingerprint.
    """
    return hashlib.sha256("\x00".join((operation, *parts)).encode()).hexdigest()


class RetryTransaction(Protocol):
    """Claims and receipts committed atomically with the enclosing mutation."""

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Reserve a principal/key pair or return its identical prior receipt.

        Conflicting fingerprints raise IdempotencyKeyReused. Expired claims may
        be replaced. Rollback
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
