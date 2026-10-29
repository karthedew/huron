"""In-memory signing keys."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from huron.core.metastore.memory import MemoryState
    from huron.core.security.broker.keys import SigningKey

__all__ = ["MemoryKeys"]


class MemoryKeys:
    """Signing keys in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def list_keys(self) -> Sequence[SigningKey]:
        """Every key, newest first."""
        return sorted(self._state.keys.values(), key=lambda key: key.created_at, reverse=True)

    async def insert_key(self, key: SigningKey) -> None:
        """Store a new key."""
        self._state.keys[key.kid] = key

    async def retire_key(self, kid: str, at: datetime) -> None:
        """Mark a key retired."""
        key = self._state.keys.get(kid)
        if key is not None and key.retired_at is None:
            self._state.keys[kid] = replace(key, retired_at=at)
