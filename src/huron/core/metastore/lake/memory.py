"""Committed lake tables, buffered transactions and transaction-scoped locks."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING

from huron.core.foundation.clock import SystemClock
from huron.core.lake.audit import AUDIT_VOCABULARY, AuditRecord
from huron.core.metastore.lake.audit import InMemoryAudit, audit_log_violation
from huron.core.metastore.lake.idempotency import ClaimRow, InMemoryClaims
from huron.core.metastore.lake.role_mappings import InMemoryRoleMappings
from huron.core.metastore.lake.signing_keys import InMemorySigningKeys
from huron.core.security.broker import Role

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Hashable, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from huron.core.foundation.clock import Clock
    from huron.core.lake.audit import AuditAction, AuditEntry, AuditObject
    from huron.core.security.broker import CatalogRef, SigningAlgorithm


class IntegrityViolation(RuntimeError):
    """A staged write broke the PostgreSQL constraint of the same name.

    The fake raises it where PostgreSQL would raise a constraint violation that the
    domain never expects, so shared scenarios can assert the backstop on either adapter.
    """

    def __init__(self, constraint: str) -> None:
        """Name the constraint that refused the row.

        Args:
            constraint: The PostgreSQL constraint name.
        """
        self.constraint = constraint
        super().__init__(constraint)


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
    catalog: CatalogRef | None
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
    audit_actions: set[tuple[AuditAction, AuditObject]] = field(default_factory=set)
    audit_log: dict[int, AuditRecord] = field(default_factory=dict)
    next_audit_id: int = 1
    idempotency_records: dict[tuple[str, str], ClaimRow] = field(default_factory=dict)


class _TableBuffer[K, V]:
    """One typed table's pending replacements and tombstones."""

    def __init__(
        self,
        committed: dict[K, V],
        check_open: Callable[[], None],
        violation: Callable[[V], str | None] | None = None,
    ) -> None:
        """Bind pending changes to their committed table and transaction lifetime.

        Args:
            committed: Live rows, shared by all transactions.
            check_open: Guard called before any read or write.
            violation: The table's row constraints, naming the first one a row breaks.
        """
        self._committed = committed
        self._check_open = check_open
        self._violation = violation
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

        Raises:
            IntegrityViolation: If the row breaks one of the table's constraints.
        """
        self._check_open()
        if self._violation is not None and (constraint := self._violation(row)) is not None:
            raise IntegrityViolation(constraint)
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


class _AuditLogBuffer:
    """Entries appended by one transaction, numbered from the log's sequence only on commit."""

    def __init__(self, tables: LakeTables, check_open: Callable[[], None]) -> None:
        """Start with no pending entries.

        Args:
            tables: Committed state holding the vocabulary, the log and its sequence.
            check_open: Guard called before any write.
        """
        self._tables = tables
        self._check_open = check_open
        self._pending: list[partial[AuditRecord]] = []

    def append(self, entries: Sequence[AuditEntry]) -> None:
        """Encode and stage a batch whole, or none of it.

        Args:
            entries: Entries in the order their ids must follow.

        Raises:
            IntegrityViolation: If an entry's row breaks an audit log constraint.
        """
        self._check_open()
        for entry in entries:
            constraint = audit_log_violation(entry, self._tables.audit_actions)
            if constraint is not None:
                raise IntegrityViolation(constraint)
        encoded = [
            partial(
                AuditRecord,
                at=entry.at,
                actor=entry.actor,
                action=entry.event.ACTION,
                object_type=entry.event.OBJECT,
                object_id=entry.object_id,
                catalog_id=entry.catalog_id,
                detail=entry.detail(),
                reason=entry.reason,
            )
            for entry in entries
        ]
        self._pending.extend(encoded)

    def _apply(self) -> None:
        """Number pending entries in staging order without yielding execution."""
        for record in self._pending:
            row_id = self._tables.next_audit_id
            self._tables.audit_log[row_id] = record(id=row_id)
            self._tables.next_audit_id = row_id + 1


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
        self.audit_log = _AuditLogBuffer(tables, self.check_open)
        self.idempotency_records = _TableBuffer(
            tables.idempotency_records, self.check_open, ClaimRow.violation
        )

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
        self.audit_log._apply()
        self.idempotency_records._apply()

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


class InMemoryLakeTransaction(InMemoryAudit, InMemoryClaims):
    """One buffered transaction that releases all its locks when it closes."""

    def __init__(self, tables: LakeTables, locks: _LockRegistry, clock: Clock) -> None:
        """Bind this transaction to the store's rows and lock registry.

        Args:
            tables: Committed state shared with the store root.
            locks: Locks shared by all the store's transactions.
            clock: The source of claim lifetimes.
        """
        self.buffer = LakeBuffer(tables)
        self._clock = clock
        self._claimed: set[tuple[str, str]] = set()
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


class InMemoryLakeStore(InMemoryRoleMappings, InMemorySigningKeys):
    """Independent committed lake state with atomic buffered transactions."""

    def __init__(self, *, clock: Clock | None = None, seed: bool = True) -> None:
        """Create empty tables and optionally load the seeded vocabularies.

        Args:
            clock: The source of claim lifetimes, the system's UTC clock when omitted.
            seed: Whether to install the four roles and the audit vocabulary.
        """
        self._clock = clock if clock is not None else SystemClock()
        self.tables = LakeTables(
            roles={row.code: row for row in ROLE_ROWS} if seed else {},
            audit_actions=set(AUDIT_VOCABULARY) if seed else set(),
        )
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
        transaction = InMemoryLakeTransaction(self.tables, self._locks, self._clock)
        try:
            yield transaction
            transaction.buffer.apply()
        finally:
            transaction.close()
            self._active.remove(task)
