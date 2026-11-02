"""Signing-key administration: list and rotate the keys that sign Huron tokens."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.security.broker.keys import KeyRing, SigningKey, generate_key
from huron.core.security.rbac import PLATFORM, Authorizer, Privilege

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import timedelta

    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["SigningKeys"]


class SigningKeys:
    """Loads the key ring and rotates keys."""

    def __init__(self, uow: UnitOfWork, clock: Clock, overlap: timedelta) -> None:
        self._uow = uow
        self._clock = clock
        self._overlap = overlap

    async def ring(self) -> KeyRing:
        """The key ring as stored now."""
        async with self._uow.transaction() as tx:
            return KeyRing(await tx.keys.list_keys(), self._overlap, self._clock)

    async def ensure_current(self, tx: Transaction) -> SigningKey | None:
        """Create a key when none is active; returns the new key, if any."""
        keys = await tx.keys.list_keys()
        if any(key.retired_at is None for key in keys):
            return None
        key = generate_key(self._clock)
        await tx.keys.insert_key(key)
        return key

    async def list(self, actor: Actor) -> Sequence[SigningKey]:
        """Every key, newest first; needs ``SIGNING_KEY_ROTATE``."""
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.SIGNING_KEY_ROTATE, PLATFORM)
            return await tx.keys.list_keys()

    async def rotate(self, actor: Actor) -> SigningKey:
        """Add a new current key and retire the previous ones."""
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.SIGNING_KEY_ROTATE, PLATFORM)
            now = self._clock.now()
            retired = [key.kid for key in await tx.keys.list_keys() if key.retired_at is None]
            for kid in retired:
                await tx.keys.retire_key(kid, now)
            key = generate_key(self._clock)
            await tx.keys.insert_key(key)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.SIGNING_KEY_ROTATE,
                ObjectType.SIGNING_KEY,
                None,
                detail={"kid": key.kid, "retired": retired},
            )
            return key
