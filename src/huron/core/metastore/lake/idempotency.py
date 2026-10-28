"""Transaction-scoped retry claims and their expiring receipts."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from huron.core.foundation.errors import IdempotencyKeyReused

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable

    from huron.core.foundation.clock import Clock
    from huron.core.foundation.retry import IdempotencyClaim, Replay
    from huron.core.metastore.lake.memory import LakeBuffer


@dataclass(frozen=True, slots=True)
class ClaimRow:
    """A request fingerprint and optional result within its fixed lifetime."""

    request_sha256: str
    replay: Replay | None
    created_at: datetime
    expires_at: datetime


class InMemoryClaims:
    """The retry writer half of an open in-memory transaction."""

    buffer: LakeBuffer
    _clock: Clock
    _claimed: set[tuple[str, str]]
    lock: Callable[[Hashable], Awaitable[None]]

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Reserve a key or replay the matching unexpired request.

        Args:
            claim: The principal's key and request fingerprint.

        Returns:
            A remembered receipt, or None for a claim without a receipt.

        Raises:
            IdempotencyKeyReused: If a live claim has a different fingerprint.
        """
        self.buffer.check_open()
        _check_claim(claim)
        key = (claim.principal, claim.key)
        if key not in self._claimed:
            await self.lock(("claim", *key))
            self._claimed.add(key)
        now = self._clock.now()
        row = self.buffer.idempotency_records.get(key)
        if row is not None and row.expires_at > now:
            if row.request_sha256 != claim.request_sha256:
                raise IdempotencyKeyReused("Idempotency key reused with a different request")
            return row.replay
        self.buffer.idempotency_records.put(
            key, ClaimRow(claim.request_sha256, None, now, now + timedelta(hours=24))
        )
        return None

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Attach a receipt to the request held by this transaction.

        Args:
            claim: The previously acquired request identity.
            replay: Its durable lake result.

        Raises:
            RuntimeError: If this transaction does not hold the matching claim.
            IntegrityViolation: If the receipt violates the lake table contract.
        """
        from huron.core.metastore.lake.memory import IntegrityViolation

        self.buffer.check_open()
        key = (claim.principal, claim.key)
        row = self.buffer.idempotency_records.get(key)
        if key not in self._claimed or row is None or row.request_sha256 != claim.request_sha256:
            raise RuntimeError("A matching claim must be acquired before remembering its receipt")
        if replay.kind not in {"catalog", "metadata_schema", "signing_key", "collection", "commit"}:
            raise IntegrityViolation("idempotency_records_replay_kind_check")
        if replay.resource_id is None:
            raise IntegrityViolation("idempotency_records_receipt")
        self.buffer.idempotency_records.put(key, replace(row, replay=replay))


def _check_claim(claim: IdempotencyClaim) -> None:
    """Apply the retry table's principal, key and fingerprint checks.

    Args:
        claim: Request identity to validate before staging.

    Raises:
        IntegrityViolation: If the claim violates a persisted CHECK.
    """
    from huron.core.metastore.lake.memory import IntegrityViolation

    constraints = {
        "idempotency_records_principal_check": 1 <= len(claim.principal) <= 160,
        "idempotency_records_key_check": 1 <= len(claim.key) <= 255,
        "idempotency_records_request_sha256_check": re.fullmatch(
            r"[0-9a-f]{64}", claim.request_sha256
        )
        is not None,
    }
    for constraint, valid in constraints.items():
        if not valid:
            raise IntegrityViolation(constraint)
