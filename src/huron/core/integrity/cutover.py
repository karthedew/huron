"""Externally authenticated, continuously fenced legacy cutover preparation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.pkg.catalog.paths import parse_revision_dir

from .generations import GenerationVerifier
from .models import FenceEvidence, MaintenanceGrant, ProtocolInventory, ProtocolTransition
from .verification import RevisionVerifier

if TYPE_CHECKING:
    from collections.abc import Callable
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
        """Verify and record the complete legacy population under uninterrupted exclusion.

        No application role is enabled here. Activation belongs to the separately
        validated deployment transition. A crash can repeat this operation with the
        same run only while the original exclusion generation remains in force.

        Args:
            run_id: Immutable retry identity for this cutover attempt.

        Returns:
            Durable report-bound transition, leaving application writers excluded.

        Raises:
            PermissionError: If external authority lacks this root's cutover grant.
            ValueError: If the controller evidence names another actor or root.
        """
        grant = await self._authority.authenticate()
        if grant.root_id != self._root_id or "cutover" not in grant.operations:
            raise PermissionError("operator is not authorized for this root's cutover")
        evidence = await self._writers.establish(grant, run_id)
        if (evidence.root_id, evidence.operator) != (grant.root_id, grant.operator):
            raise ValueError("controller evidence disagrees with authenticated authority")
        with self._storage.claim():
            result = await self._prepare_owned(grant, evidence, run_id)
        await self._writers.certify(result)
        return result

    async def validate(self, transition: ProtocolTransition) -> None:
        """Admit a receipt only through the live authority's complete certificate validation.

        Args:
            transition: Previously returned or indeterminately acknowledged receipt.

        Raises:
            PermissionError: If the caller or receipt belongs to another maintenance root.
        """
        grant = await self._authority.authenticate()
        if grant.root_id != self._root_id or transition.root_id != grant.root_id:
            raise PermissionError("certificate belongs to another maintenance root")
        if "cutover" not in grant.operations or transition.actor != grant.operator:
            raise PermissionError("operator is not authorized for this certificate")
        await self._writers.validate_certificate(transition)

    async def _prepare_owned(
        self, grant: MaintenanceGrant, evidence: FenceEvidence, run_id: UUID
    ) -> ProtocolTransition:
        fence = _Fence(self._writers, self._roles, evidence)
        await self._roles.exclude(evidence.old_roles, evidence.new_role)
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
        await self._publish(f"reports/{run_id}.json", inventory.canonical, fence)
        transition = self._transition(inventory)
        await self._publish(f"{transition.sequence:06d}.json", transition.canonical, fence)
        return transition

    def _transition(self, inventory: ProtocolInventory) -> ProtocolTransition:
        sequence = 1
        while True:
            try:
                existing = self._storage.read_control("protocol", f"{sequence:06d}.json")
            except FileNotFoundError:
                return ProtocolTransition.bind(
                    inventory, sequence=sequence, instant=self._now(), code_digest=self._code_digest
                )
            transition = ProtocolTransition.decode(existing)
            if transition.run_id == inventory.run_id:
                transition.validate_inventory(inventory)
                return transition
            sequence += 1

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
                await self.roles.check(self.evidence.old_roles, self.evidence.new_role)
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
