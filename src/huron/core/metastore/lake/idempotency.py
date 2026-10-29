"""The lake's retry claims: their table row, constraints and in-memory transaction half."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from huron.core.foundation.errors import IdempotencyKeyReused

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable
    from datetime import datetime

    from huron.core.foundation.clock import Clock
    from huron.core.foundation.retry import IdempotencyClaim, Replay
    from huron.core.metastore.lake.memory import LakeBuffer

CLAIM_LIFETIME: Final = timedelta(hours=24)
LAKE_REPLAY_KINDS: Final = frozenset(
    {"catalog", "metadata_schema", "signing_key", "collection", "commit"}
)
_PRINCIPAL_MAX: Final = 160
_KEY_MAX: Final = 255
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ClaimRow:
    """One `lake.idempotency_records` row: a claim, its receipt once remembered, its lifetime."""

    claim: IdempotencyClaim
    replay: Replay | None
    created_at: datetime
    expires_at: datetime

    def live_at(self, instant: datetime) -> bool:
        """Whether the claim still binds its key at an instant.

        Args:
            instant: The time of the competing claim.

        Returns:
            True before the claim expires; every receipt kind expires alike.
        """
        return instant < self.expires_at

    def violation(self) -> str | None:
        """Name the first table constraint this row would violate.

        Returns:
            The PostgreSQL constraint name, or None when the row is acceptable.
        """
        claim = self.claim
        holds = {
            "idempotency_records_principal_check": 1 <= len(claim.principal) <= _PRINCIPAL_MAX,
            "idempotency_records_key_check": 1 <= len(claim.key) <= _KEY_MAX,
            "idempotency_records_request_sha256_check": bool(
                _SHA256.fullmatch(claim.request_sha256)
            ),
            "idempotency_records_replay_kind_check": self.replay is None
            or self.replay.kind in LAKE_REPLAY_KINDS,
            "idempotency_records_lifetime": self.expires_at > self.created_at,
        }
        return next((constraint for constraint, held in holds.items() if not held), None)


class InMemoryClaims:
    """The retry half of an open in-memory transaction."""

    buffer: LakeBuffer
    lock: Callable[[Hashable], Awaitable[None]]
    _clock: Clock
    _claimed: set[tuple[str, str]]

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Reserve a principal's key, or replay the live claim with the same fingerprint.

        The key stays locked until this transaction ends, so a concurrent claim of it
        waits and then sees this transaction's outcome.

        Args:
            claim: The principal's key and request fingerprint.

        Returns:
            The live claim's receipt (None until one is remembered), or None for a new claim.

        Raises:
            IdempotencyKeyReused: If a live claim on the key has another fingerprint.
        """
        key = (claim.principal, claim.key)
        if key not in self._claimed:
            await self.lock(("idempotency_records", *key))
            self._claimed.add(key)
        now = self._clock.now()
        row = self.buffer.idempotency_records.get(key)
        if row is not None and row.live_at(now):
            if row.claim.request_sha256 != claim.request_sha256:
                raise IdempotencyKeyReused("Idempotency key reused with a different request")
            return row.replay
        self.buffer.idempotency_records.put(key, ClaimRow(claim, None, now, now + CLAIM_LIFETIME))
        return None

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Attach the receipt to the claim this transaction holds.

        Args:
            claim: The claim this transaction acquired.
            replay: The created resource's receipt.

        Raises:
            RuntimeError: If this transaction does not hold exactly this claim.
        """
        key = (claim.principal, claim.key)
        row = self.buffer.idempotency_records.get(key)
        if key not in self._claimed or row is None or row.claim != claim:
            raise RuntimeError("A receipt needs the claim this transaction holds")
        self.buffer.idempotency_records.put(key, replace(row, replay=replay))
