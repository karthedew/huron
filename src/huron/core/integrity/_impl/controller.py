"""Durable verification epochs, evidence admission and application restart exclusion."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..models import ControllerState, FenceEvidence, ProtocolInventory, ProtocolTransition

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from ..models import ControlledRoot, DeploymentIdentity, MaintenanceGrant
    from ..ports import (
        ControllerAuthority,
        ControllerDeployment,
        ControllerStateStore,
        DatabaseExclusion,
        EvidenceStorage,
    )


class ControllerAdmission:
    """Own one serialized controller's durable verification epoch and restart admission.

    The application holds exclusive state ownership and serializes public operations.
    Construction binds persisted deployment/storage identity and advances the start
    epoch before the application can serve any requests. No full scan runs here.
    """

    def __init__(
        self,
        authority: ControllerAuthority,
        deployment: ControllerDeployment,
        state: ControllerStateStore,
        storage: EvidenceStorage,
        database: Callable[[], AbstractAsyncContextManager[DatabaseExclusion]],
        *,
        identity: DeploymentIdentity,
        old_roles: tuple[str, ...],
        new_role: str,
    ) -> None:
        """Bind injected capabilities and mint the controller-start epoch.

        Args:
            authority: External peer authentication and distinct operator grants.
            deployment: Validated live observations and fixed process control.
            state: Durable controller authority state, exclusively owned by this process.
            storage: Stored protocol evidence and its exclusive maintenance claim.
            database: Application-owned database exclusion resource lifetime.
            identity: Deployment/storage identity captured when configuring process control.
            old_roles: Legacy application identities excluded by cutover.
            new_role: Successor application identity that must also remain excluded.
        """
        self._authority = authority
        self._deployment = deployment
        self._persistence = state
        self._storage = storage
        self._database = database
        self._old_roles = old_roles
        self._new_role = new_role
        self._state = state.load() or ControllerState(
            root_id=identity.root_id,
            controller_id=identity.controller_id,
            device=identity.device,
            inode=identity.inode,
            composition=identity.composition,
            generation=0,
        )
        self._observe_root()
        self._advance()

    def authenticate(self, peer_uid: int) -> MaintenanceGrant:
        """Require authenticated authority for this controller's maintenance root.

        A grant without this root's cutover authority raises ``PermissionError``.

        Args:
            peer_uid: Peer identity authenticated externally by the application.

        Returns:
            Exact root/operator maintenance grant.
        """
        return self._authority.authenticate(peer_uid).require_cutover(self._state.root_id)

    def restart(self, peer_uid: int) -> str:
        """Admit the fixed application only while no durable cutover run excludes it.

        Args:
            peer_uid: Externally authenticated invoking operator.

        Returns:
            Newly started application process identity.

        Raises:
            ValueError: If a durable fence excludes application starts.
        """
        self._authority.require_restart(peer_uid)
        if self._state.run_id is not None:
            raise ValueError("application restart is excluded by the durable cutover fence")
        with self._observing():
            self._observe_root()
            return self._deployment.start()

    def describe(self, peer_uid: int) -> ControlledRoot:
        """Bind authorized inspection to the live protected storage namespace.

        Args:
            peer_uid: Externally authenticated maintenance operator.

        Returns:
            Live root identity after deployment and storage validation.
        """
        self.authenticate(peer_uid)
        with self._observing():
            return self._observe_root()

    async def establish(self, peer_uid: int, run_id: UUID) -> FenceEvidence:
        """Persist a new exclusion epoch before terminating every observed writer.

        Args:
            peer_uid: Externally authenticated maintenance operator.
            run_id: Audit and database-idempotence identity of this cutover attempt.

        Returns:
            Receipt naming the new generation and observed writer/database identities.
        """
        grant = self.authenticate(peer_uid)
        with self._observing():
            self._observe_root()
            writers = self._deployment.writers()
            async with self._database() as roles:
                database = await roles.identify()
        self._advance(
            run_id=run_id,
            operator=grant.operator,
            writers=tuple(sorted(writers)),
            database=database,
        )
        with self._observing():
            for writer in writers:
                self._deployment.terminate(writer)
        evidence = self._evidence()
        self.check(peer_uid, evidence)
        return evidence

    def check(self, peer_uid: int, evidence: FenceEvidence) -> None:
        """Observe exclusion afresh, then require the exact live epoch and operator.

        Args:
            peer_uid: Externally authenticated maintenance operator.
            evidence: Receipt returned by ``establish``, compared whole.

        Raises:
            ValueError: If writers remain, the generation changed or the operator differs.
        """
        grant = self.authenticate(peer_uid)
        with self._observing():
            self._observe_root()
            if self._deployment.writers():
                raise ValueError("controller exclusion was lost or a foreign writer appeared")
        if not self._live(evidence):
            raise ValueError("controller exclusion generation changed")
        if evidence.operator != grant.operator:
            raise ValueError("receipt names another maintenance operator")

    def abandon(self, peer_uid: int, evidence: FenceEvidence) -> None:
        """End only the epoch this receipt names, without observing or enabling writers.

        Args:
            peer_uid: Externally authenticated maintenance operator.
            evidence: Receipt whose run did not complete; stale receipts are ignored.
        """
        self.authenticate(peer_uid)
        if self._live(evidence):
            self._advance()

    async def validate(self, peer_uid: int, transition: ProtocolTransition) -> None:
        """Admit exact stored evidence between complete live fence observations.

        Args:
            peer_uid: Externally authenticated maintenance operator or consumer.
            transition: Record exactly as stored under ``protocol/{sequence:06d}.json``.

        Raises:
            ValueError: If the record's run disagrees with current controller ownership.
        """
        self.check(peer_uid, transition.fence)
        if transition.run_id != self._state.run_id:
            raise ValueError("record run differs from current controller ownership")
        await self._validate_evidence(transition)
        self.check(peer_uid, transition.fence)

    async def _validate_evidence(self, transition: ProtocolTransition) -> None:
        name = f"{transition.sequence:06d}.json"
        with self._observing(), self._storage.claim():
            stored = _stored(self._storage, "protocol", name)
            report = _stored(self._storage, "protocol/reports", name)
        if stored is None or report is None:
            raise ValueError("no stored evidence at the presented sequence")
        if ProtocolTransition.decode(stored) != transition:
            raise ValueError("stored protocol record differs from presented receipt")
        transition.validate_inventory(ProtocolInventory.decode(report))
        with self._observing():
            async with self._database() as roles:
                await roles.check(transition.fence)

    def _observe_root(self) -> ControlledRoot:
        observation = self._deployment.observe()
        if self._state.identity != observation.identity:
            raise ValueError("controller root or deployment identity changed")
        return observation.root

    def _advance(self, **changes: object) -> None:
        advanced = self._state.model_copy(
            update={**changes, "generation": self._state.generation + 1}
        )
        try:
            self._persistence.persist(advanced)
        finally:
            # A failed write must not leave the old receipt admissible in memory.
            # The next controller start advances the persisted epoch again.
            self._state = advanced

    @contextmanager
    def _observing(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self._advance()
            raise

    def _live(self, evidence: FenceEvidence) -> bool:
        return self._state.database is not None and evidence == self._evidence()

    def _evidence(self) -> FenceEvidence:
        return FenceEvidence.model_validate(
            {
                "controller_id": self._state.controller_id,
                "root_id": self._state.root_id,
                "generation": self._state.generation,
                "operator": self._state.operator,
                "terminated_writers": self._state.writers,
                "old_roles": self._old_roles,
                "new_role": self._new_role,
                "database": self._state.database,
            }
        )


def _stored(store: EvidenceStorage, directory: str, name: str) -> bytes | None:
    try:
        return store.read_control(directory, name)
    except FileNotFoundError:
        return None
