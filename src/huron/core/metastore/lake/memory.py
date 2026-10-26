"""Committed lake tables, buffered transactions and transaction-scoped locks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from huron.core.security.broker import Role

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Hashable, Mapping
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.broker import SigningAlgorithm


@dataclass(frozen=True, slots=True)
class RoleRow:
    """One seeded role's code, display title, rank and permitted scope."""

    code: str
    title: str
    rank: int
    scope: str


ROLE_ROWS = tuple(
    RoleRow(role.code, role.title, int(role), "catalog" if role.catalog_scoped else "organization")
    for role in Role
)


@dataclass(frozen=True, slots=True)
class LdapGroupRow:
    """A directory group's permanently reserved POSIX identifier."""

    name: str
    posix_gid: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RoleMappingRow:
    """A group's current role in one catalog or the organization."""

    ldap_group: str
    catalog_id: UUID | None
    role_code: str
    role_scope: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class SigningKeyRow:
    """Public signing material and its registration and lifetime facts."""

    kid: str
    alg: SigningAlgorithm
    public_jwk: Mapping[str, str]
    private_ref: str
    active_from: datetime
    retired_at: datetime | None
    created_at: datetime
    created_by: str

    def __post_init__(self) -> None:
        """Own an immutable copy of the public JWK members."""
        object.__setattr__(self, "public_jwk", MappingProxyType(dict(self.public_jwk)))


@dataclass(slots=True)
class LakeTables:
    """Committed rows indexed by each table's primary or unique key."""

    roles: dict[str, RoleRow] = field(default_factory=dict)
    ldap_groups: dict[str, LdapGroupRow] = field(default_factory=dict)
    group_role_map: dict[tuple[str, UUID | None], RoleMappingRow] = field(default_factory=dict)
    signing_keys: dict[str, SigningKeyRow] = field(default_factory=dict)


class _TableBuffer[K, V]:
    """One typed table's pending replacements and tombstones."""

    def __init__(self, committed: dict[K, V], check_open: Callable[[], None]) -> None:
        """Bind pending changes to their committed table and transaction lifetime.

        Args:
            committed: Live rows, shared by all transactions.
            check_open: Guard called before any read or write.
        """
        self._committed = committed
        self._check_open = check_open
        self._changes: dict[K, V | None] = {}

    def get(self, key: K) -> V | None:
        """Read a pending change first, falling back to committed state.

        Args:
            key: The row's primary or unique key.

        Returns:
            The visible row, or None for a missing or deleted row.
        """
        self._check_open()
        return self._changes.get(key, self._committed.get(key))

    def put(self, key: K, row: V) -> None:
        """Stage a row without changing committed state.

        Args:
            key: The row's primary or unique key.
            row: The immutable replacement row.
        """
        self._check_open()
        self._changes[key] = row

    def delete(self, key: K) -> None:
        """Stage a deletion, including for a row absent from committed state.

        Args:
            key: The row's primary or unique key.
        """
        self._check_open()
        self._changes[key] = None

    def _apply(self) -> None:
        """Apply this table's pending changes without yielding execution."""
        for key, row in self._changes.items():
            if row is None:
                self._committed.pop(key, None)
            else:
                self._committed[key] = row


class LakeBuffer:
    """An open transaction's typed read-through changes across every lake table."""

    def __init__(self, tables: LakeTables) -> None:
        """Create an empty buffer over committed rows.

        Args:
            tables: The store's committed tables.
        """
        self._open = True
        self.roles = _TableBuffer(tables.roles, self.check_open)
        self.ldap_groups = _TableBuffer(tables.ldap_groups, self.check_open)
        self.group_role_map = _TableBuffer(tables.group_role_map, self.check_open)
        self.signing_keys = _TableBuffer(tables.signing_keys, self.check_open)

    def check_open(self) -> None:
        """Refuse reads and writes after the transaction has exited.

        Raises:
            RuntimeError: If the buffer has closed.
        """
        if not self._open:
            raise RuntimeError("Lake transaction is closed")

    def apply(self) -> None:
        """Commit every staged table synchronously, without yielding to other tasks."""
        self.check_open()
        self.roles._apply()
        self.ldap_groups._apply()
        self.group_role_map._apply()
        self.signing_keys._apply()

    def close(self) -> None:
        """Invalidate all references to this transaction's buffered tables."""
        self._open = False


class _ReadWriteLock:
    """Coexisting catalog readers or one exclusive catalog writer."""

    def __init__(self) -> None:
        """Start with no holders and an event for the next release."""
        self._readers = 0
        self._writer = False
        self._changed = asyncio.Event()

    async def acquire(self, *, shared: bool) -> None:
        """Wait until the requested mode can coexist with current holders.

        Args:
            shared: Whether to take a reader instead of an exclusive writer.
        """
        while self._writer or (not shared and self._readers):
            await self._changed.wait()
        if shared:
            self._readers += 1
        else:
            self._writer = True

    def release(self, *, shared: bool) -> None:
        """Release a holder synchronously, including during cancellation cleanup.

        Args:
            shared: The mode acquired by this holder.
        """
        if shared:
            self._readers -= 1
        else:
            self._writer = False
        self._changed.set()
        self._changed = asyncio.Event()


@dataclass(slots=True)
class _LockRegistry:
    """Store-wide exclusive keys and catalog reader/writer keys."""

    exclusive: dict[Hashable, asyncio.Lock] = field(default_factory=dict)
    catalogs: dict[Hashable, _ReadWriteLock] = field(default_factory=dict)


class InMemoryLakeTransaction:
    """One buffered transaction that releases all its locks when it closes."""

    def __init__(self, tables: LakeTables, locks: _LockRegistry) -> None:
        """Bind this transaction to the store's rows and lock registry.

        Args:
            tables: Committed state shared with the store root.
            locks: Locks shared by all the store's transactions.
        """
        self.buffer = LakeBuffer(tables)
        self._locks = locks
        self._releases: list[Callable[[], None]] = []

    async def lock(self, key: Hashable) -> None:
        """Hold one exclusive key until this transaction exits.

        Args:
            key: A resource identity, including its lock category.
        """
        self.buffer.check_open()
        lock = self._locks.exclusive.setdefault(key, asyncio.Lock())
        await lock.acquire()
        self._releases.append(lock.release)

    async def lock_catalog(self, key: Hashable, *, shared: bool) -> None:
        """Hold a shared or exclusive catalog lock until transaction exit.

        Args:
            key: The catalog identity.
            shared: Whether concurrent readers may hold the same catalog.
        """
        self.buffer.check_open()
        lock = self._locks.catalogs.setdefault(key, _ReadWriteLock())
        await lock.acquire(shared=shared)
        self._releases.append(lambda: lock.release(shared=shared))

    def close(self) -> None:
        """Close buffered access and release held locks without a cancellation point."""
        self.buffer.close()
        for release in reversed(self._releases):
            release()
        self._releases.clear()


class InMemoryLakeStore:
    """Independent committed lake state with atomic buffered transactions."""

    def __init__(self, *, seed: bool = True) -> None:
        """Create empty tables and optionally load the role vocabulary.

        Args:
            seed: Whether to install the four built-in roles.
        """
        self.tables = LakeTables(roles={row.code: row for row in ROLE_ROWS} if seed else {})
        self._locks = _LockRegistry()
        self._active: set[asyncio.Task[object] | None] = set()

    async def ping(self) -> None:
        """Confirm that this in-process store is available."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[InMemoryLakeTransaction]:
        """Commit on clean exit, otherwise discard changes and propagate the exception.

        Yields:
            An open transaction over this store's committed state.

        Raises:
            RuntimeError: If this task already has an open transaction on this store.
        """
        task = asyncio.current_task()
        if task in self._active:
            raise RuntimeError("Lake transactions cannot be nested")
        self._active.add(task)
        transaction = InMemoryLakeTransaction(self.tables, self._locks)
        try:
            yield transaction
            transaction.buffer.apply()
        finally:
            transaction.close()
            self._active.remove(task)
