"""Externally authenticated, continuously fenced legacy cutover preparation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from itertools import count
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.core.raw.paths import parse_revision_dir

from .generations import GenerationVerifier
from .models import FenceEvidence, MaintenanceGrant, ProtocolInventory, ProtocolTransition
from .verification import RevisionVerifier

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from datetime import datetime
    from uuid import UUID

    from .ports import (
        DatabaseExclusion,
        LegacyMaintenance,
        LegacyStorage,
        MaintenanceAuthority,
        WriterExclusion,
    )


class CutoverService:
    """Coordinate complete legacy verification without treating observations as exclusion."""

    def __init__(
        self,
        authority: MaintenanceAuthority,
        writers: WriterExclusion,
        roles: DatabaseExclusion,
        database: LegacyMaintenance,
        storage: LegacyStorage,
        *,
        root_id: UUID,
        catalog_root: PurePosixPath,
        code_digest: str,
        now: Callable[[], datetime],
        check_interval: float = 1.0,
    ) -> None:
        """Bind external authorities, maintenance adapters and audit inputs.

        Args:
            authority: Live external authentication for the invoking operator.
            writers: Enforced writer termination and restart exclusion.
            roles: Dedicated application-role database fencing.
            database: Trusted inventory and schema-0010 maintenance.
            storage: No-follow streaming inspection and durable protocol storage.
            root_id: Controller-owned immutable root identity.
            catalog_root: Legacy catalog's logical storage path.
            code_digest: Immutable verification implementation digest.
            now: Injected audit clock.
            check_interval: Maximum interval between live fence observations.

        Raises:
            ValueError: If fence checking cannot make forward progress.
        """
        if check_interval <= 0:
            raise ValueError("fence check interval must be positive")
        self._authority = authority
        self._writers = writers
        self._roles = roles
        self._database = database
        self._storage = storage
        self._root_id = root_id
        self._catalog_root = catalog_root
        self._verifier = RevisionVerifier(storage, catalog_root)
        self._code_digest = code_digest
        self._now = now
        self._check_interval = check_interval

    async def prepare(self, run_id: UUID) -> ProtocolTransition:
        """Verify and record the complete legacy population under one exclusion epoch.

        No application role is enabled here. Activation belongs to the separately
        validated deployment transition. Every invocation appends one report and one
        record at the next free sequence number; an invocation that does not return
        ends its own epoch, so nothing under ``protocol/`` is reused or admitted from
        an earlier attempt. A root owned by another coordinator, an authority refusal
        and a lost reply propagate unchanged from the claim, the authority and the scan.
        Missing root/operation authority raises ``PermissionError`` before claiming storage.

        Args:
            run_id: Audit and database-idempotence identity of this cutover attempt.

        Returns:
            Durable record admitted by the live authority, leaving application writers excluded.

        Raises:
            ValueError: If the controller evidence names another actor or root.
        """
        grant = (await self._authority.authenticate()).require_cutover(self._root_id)
        with self._storage.claim():
            evidence = await self._writers.establish(grant, run_id)
            async with self._abandoning(evidence):
                if (evidence.root_id, evidence.operator) != (grant.root_id, grant.operator):
                    raise ValueError("controller evidence disagrees with authenticated authority")
                result = await self._prepare_owned(grant, evidence, run_id)
        await self._writers.validate(result)
        return result

    async def validate(self, transition: ProtocolTransition) -> None:
        """Admit a record only through the live authority's complete validation.

        A caller or record for another root/operator is refused with ``PermissionError``.

        Args:
            transition: Record to admit, exactly as stored under ``protocol/{sequence:06d}.json``.
        """
        grant = await self._authority.authenticate()
        await self._admit(grant, transition)

    async def _admit(self, grant: MaintenanceGrant, transition: ProtocolTransition) -> None:
        if grant.root_id != self._root_id or transition.root_id != grant.root_id:
            raise PermissionError("record belongs to another maintenance root")
        if not grant.permits_cutover(self._root_id) or transition.actor != grant.operator:
            raise PermissionError("operator is not authorized for this record")
        await self._writers.validate(transition)

    async def validate_sequence(self, sequence: int) -> ProtocolTransition:
        """Load and admit one stored record through the live authority without rescanning.

        Missing root/operation authority raises ``PermissionError`` before reading storage.

        Args:
            sequence: Stored record number under this root's ``protocol/`` directory.

        Returns:
            The exact canonical record admitted by the live controller.
        """
        grant = (await self._authority.authenticate()).require_cutover(self._root_id)
        stored = self._storage.read_control("protocol", f"{sequence:06d}.json")
        transition = ProtocolTransition.decode(stored)
        await self._admit(grant, transition)
        return transition

    @asynccontextmanager
    async def _abandoning(self, evidence: FenceEvidence) -> AsyncIterator[None]:
        try:
            yield
        except BaseException:
            with suppress(Exception):
                await self._writers.abandon(evidence)
            raise

    async def _prepare_owned(
        self, grant: MaintenanceGrant, evidence: FenceEvidence, run_id: UUID
    ) -> ProtocolTransition:
        fence = _Fence(self._writers, self._roles, evidence)
        await self._roles.exclude(evidence)
        await fence.check()
        stop = asyncio.Event()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(fence.monitor(stop, self._check_interval))
            try:
                result = await self._record(grant, fence, run_id)
            finally:
                stop.set()
        return result

    async def _record(
        self, grant: MaintenanceGrant, fence: _Fence, run_id: UUID
    ) -> ProtocolTransition:
        evidence = fence.evidence
        scanned = []
        generations = await asyncify(GenerationVerifier(self._storage).verify)(
            await self._database.generation_records()
        )
        paths = set(self._storage.revision_paths())
        paths.update(
            str(PurePosixPath(path).relative_to(self._catalog_root))
            for path in await self._database.revision_paths()
        )
        for path in sorted(paths):
            await fence.check()
            identity = parse_revision_dir(PurePosixPath("/"), PurePosixPath("/") / path)
            existing = await self._database.lookup(identity)
            scanned.append(await asyncify(self._verifier.verify)(path, existing))
        inventory = ProtocolInventory(
            run_id=run_id,
            root_id=self._root_id,
            fence=evidence,
            revisions=tuple(entry for entry, _ in scanned),
            generations=generations,
        )
        await fence.check()
        await self._database.resolve(
            grant.operator,
            grant.root_id,
            run_id,
            tuple((record, entry.findings) for entry, record in scanned),
        )
        await fence.check()
        sequence = await asyncify(self._next_sequence)()
        await self._publish(f"reports/{sequence:06d}.json", inventory.canonical, fence)
        transition = ProtocolTransition.bind(
            inventory, sequence=sequence, instant=self._now(), code_digest=self._code_digest
        )
        await self._publish(f"{sequence:06d}.json", transition.canonical, fence)
        return transition

    def _next_sequence(self) -> int:
        return next(sequence for sequence in count(1) if not self._occupied(sequence))

    def _occupied(self, sequence: int) -> bool:
        name = f"{sequence:06d}.json"
        for directory in ("protocol/reports", "protocol"):
            try:
                self._storage.read_control(directory, name)
            except FileNotFoundError:
                continue
            return True
        return False

    async def _publish(self, path: str, payload: bytes, fence: _Fence) -> None:
        await fence.check()
        await _settled_write(self._storage, path, payload)
        await fence.check()


@dataclass
class _Fence:
    writers: WriterExclusion
    roles: DatabaseExclusion
    evidence: FenceEvidence
    _lost: bool = field(default=False, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def check(self) -> None:
        async with self._lock:
            if self._lost:
                raise ValueError("exclusion was lost during this verification run")
            try:
                await self.writers.check(self.evidence)
                await self.roles.check(self.evidence)
            except Exception:
                self._lost = True
                raise

    async def monitor(self, stop: asyncio.Event, interval: float) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                await self.check()


async def _settled_write(storage: LegacyStorage, path: str, payload: bytes) -> None:
    task = asyncio.create_task(asyncio.to_thread(storage.write_evidence, path, payload))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError
