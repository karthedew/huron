"""Transaction-scoped retry resolution shared by catalog publication workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from huron.core.foundation.retry import IdempotencyClaim, RetryTransaction


async def claimed_result[RecordT](
    writer: RetryTransaction,
    claim: IdempotencyClaim,
    read: Callable[[UUID], Awaitable[RecordT]],
) -> RecordT | None:
    """Stake a write's idempotency claim, returning what a prior identical claim produced.

    Args:
        writer: The open transaction's writer.
        claim: The claim this write is staking.
        read: Given the id ``claim`` was originally remembered under,
            returns the resource it named. A release ignores the id,
            since its own read is keyed by dataset and tag instead.

    Returns:
        The resource an earlier, identical request already created, or
        ``None`` when no live claim exists and this transaction is the
        one to perform the write.
    """
    replay = await writer.claim(claim)
    if replay is None:
        return None
    return await read(replay.resource_id)
