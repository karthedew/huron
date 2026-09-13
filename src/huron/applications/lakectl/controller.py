"""Persistent restart admission for one private local Compose application volume."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg

from huron.core.integrity.models import (
    FenceEvidence,
    MaintenanceGrant,
    ProtocolInventory,
    ProtocolTransition,
)
from huron.pkg.metastore.maintenance import PostgresRoleExclusion
from huron.pkg.rawstore.maintenance import MaintenanceStore

from .engine import LocalEngine, require_local_administrator
from .settings import ControlledRoot, ControllerState, MaintenanceSettings, private_document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from uuid import UUID

    from .engine import Container
    from .settings import ControllerSettings


class ManagedComposeController:
    """Own application restart authority and preserve exclusion across process restarts."""

    def __init__(self, settings: ControllerSettings) -> None:
        """Validate local authority, load private configuration once and mint the start epoch.

        Args:
            settings: Private administrator-provisioned deployment configuration.
        """
        require_local_administrator()
        self._settings = settings
        self._maintenance = MaintenanceSettings.load(settings.maintenance_path)
        self._engine = LocalEngine(settings.engine_socket)
        self._specification = settings.application_specification()
        self._image = self._engine.image_identity(str(self._specification["Image"]))
        self._volume = self._engine.volume_path(settings.volume_name)
        self._composition = hashlib.sha256(private_document(settings.compose_path)).hexdigest()
        self._state = self._load_state()
        self._check_volume()
        self._advance()

    def authenticate(self, peer_uid: int) -> MaintenanceGrant:
        """Authorize the kernel-authenticated peer for this root's maintenance.

        Args:
            peer_uid: UID obtained from the connected Unix socket's peer credentials.

        Returns:
            Exact root/operator maintenance grant.

        Raises:
            PermissionError: If the peer is not an authorized maintenance operator.
        """
        if peer_uid not in self._settings.cutover_operators:
            raise PermissionError("operator has no maintenance grant for this root")
        return MaintenanceGrant(
            root_id=self._settings.root_id,
            operator=f"local:{peer_uid}",
            operations=frozenset({"cutover"}),
        )

    def restart(self, peer_uid: int) -> str:
        """Admit only the fixed legacy application while no exclusion is active.

        Args:
            peer_uid: Kernel-authenticated invoking operator.

        Returns:
            Newly created application container identity.

        Raises:
            PermissionError: If the peer lacks restart authority.
            ValueError: If a durable fence excludes application starts.
        """
        if peer_uid not in self._settings.restart_operators:
            raise PermissionError("operator has no application restart grant")
        if self._state.run_id is not None:
            raise ValueError("application restart is excluded by the durable cutover fence")
        with self._observing():
            self._check_volume()
            return self._engine.start(self._specification)

    def describe(self, peer_uid: int) -> ControlledRoot:
        """Bind maintenance inspection to the actual protected storage namespace.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.

        Returns:
            Live root identity after deployment and storage validation.
        """
        self.authenticate(peer_uid)
        with self._observing():
            self._check_volume()
        return ControlledRoot(
            root_id=self._state.root_id,
            path=self._volume,
            owner_uid=self._settings.owner_uid,
            device=self._state.device,
            inode=self._state.inode,
        )

    async def establish(self, peer_uid: int, run_id: UUID) -> FenceEvidence:
        """Mint a new exclusion epoch, persist it, then terminate every application volume holder.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            run_id: Audit and database-idempotence identity of this cutover attempt.

        Returns:
            Receipt naming the new generation, operator, the writers this call terminated,
            the excluded roles and the maintenance database identity observed before minting.
        """
        grant = self.authenticate(peer_uid)
        with self._observing():
            self._check_volume()
            writers = self._writers()
            async with self._database() as roles:
                database = await roles.identify()
        self._advance(
            run_id=run_id,
            operator=grant.operator,
            writers=tuple(sorted(writer.identifier for writer in writers)),
            database=database,
        )
        with self._observing():
            for writer in writers:
                self._engine.terminate(writer.identifier)
        evidence = self._evidence()
        self.check(peer_uid, evidence)
        return evidence

    def check(self, peer_uid: int, evidence: FenceEvidence) -> None:
        """Observe the volume and writer inventory afresh, then require the live epoch.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            evidence: Receipt returned by ``establish``, compared whole.

        Raises:
            ValueError: If a writer holds the volume, the receipt names another
                generation or database, or the peer is not the receipt's operator.
        """
        grant = self.authenticate(peer_uid)
        with self._observing():
            self._check_volume()
            if self._writers():
                raise ValueError("controller exclusion was lost or a foreign writer appeared")
        if not self._live(evidence):
            raise ValueError("controller exclusion generation changed")
        if evidence.operator != grant.operator:
            raise ValueError("receipt names another maintenance operator")

    def abandon(self, peer_uid: int, evidence: FenceEvidence) -> None:
        """End the epoch this receipt names, observing nothing.

        A receipt that does not name the live epoch is ignored, so a stale or foreign
        receipt cannot end a newer epoch.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            evidence: Receipt whose run did not complete.
        """
        self.authenticate(peer_uid)
        if self._live(evidence):
            self._advance()

    async def validate(self, peer_uid: int, transition: ProtocolTransition) -> None:
        """Admit a stored record only under the live epoch and fresh complete observations.

        Args:
            peer_uid: Kernel-authenticated maintenance operator or consumer.
            transition: Record exactly as stored under ``protocol/{sequence:06d}.json``.

        Raises:
            ValueError: If the record's run disagrees with the established run.
        """
        self.check(peer_uid, transition.fence)
        if transition.run_id != self._state.run_id:
            raise ValueError("record run differs from current controller ownership")
        await self._validate_evidence(transition)
        self.check(peer_uid, transition.fence)

    async def _validate_evidence(self, transition: ProtocolTransition) -> None:
        name = f"{transition.sequence:06d}.json"
        with self._observing():
            store = MaintenanceStore(self._volume, self._settings.owner_uid)
            with store.claim():
                stored = _stored(store, "protocol", name)
                report = _stored(store, "protocol/reports", name)
        if stored is None or report is None:
            raise ValueError("no stored evidence at the presented sequence")
        if ProtocolTransition.decode(stored) != transition:
            raise ValueError("stored protocol record differs from presented receipt")
        transition.validate_inventory(ProtocolInventory.decode(report))
        with self._observing():
            async with self._database() as roles:
                await roles.check(transition.fence)

    @asynccontextmanager
    async def _database(self) -> AsyncIterator[PostgresRoleExclusion]:
        async with asyncpg.create_pool(self._maintenance.database_url.get_secret_value()) as pool:
            yield PostgresRoleExclusion(pool)

    def _writers(self) -> tuple[Container, ...]:
        writers = []
        for container in self._engine.inventory():
            _require_isolated_container(container)
            for mount in container.mounts:
                if mount.name == self._settings.volume_name:
                    if container.image != self._image or Path(mount.source) != self._volume:
                        raise ValueError("foreign application identity holds the protected volume")
                    writers.append(container)
                elif _exposes(mount.source, self._volume) or _exposes(
                    mount.source, self._settings.engine_socket
                ):
                    raise ValueError(
                        "foreign storage or daemon access prevents complete writer inventory"
                    )
        return tuple(writers)

    def _load_state(self) -> ControllerState:
        path = self._settings.state_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private_directory(path.parent)
        try:
            return ControllerState.model_validate_json(private_document(path))
        except FileNotFoundError:
            info = self._volume.stat()
            return ControllerState(
                root_id=self._settings.root_id,
                controller_id=self._settings.controller_id,
                device=info.st_dev,
                inode=info.st_ino,
                composition=self._composition,
                generation=0,
            )

    def _check_volume(self) -> None:
        path = self._engine.volume_path(self._settings.volume_name)
        info = path.stat()
        expected = (
            self._settings.root_id,
            self._settings.controller_id,
            info.st_dev,
            info.st_ino,
            hashlib.sha256(private_document(self._settings.compose_path)).hexdigest(),
        )
        actual = (
            self._state.root_id,
            self._state.controller_id,
            self._state.device,
            self._state.inode,
            self._state.composition,
        )
        if expected != actual:
            raise ValueError("controller root or deployment identity changed")

    def _advance(self, **changes: object) -> None:
        advanced = self._state.model_copy(
            update={**changes, "generation": self._state.generation + 1}
        )
        try:
            self._persist(advanced)
        finally:
            # Memory adopts the new epoch even when the write fails, so this process
            # keeps refusing the old receipt; the next start advances disk again.
            self._state = advanced

    def _persist(self, state: ControllerState) -> None:
        path = self._settings.state_path
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(state.model_dump_json().encode())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            Path(temporary).unlink(missing_ok=True)

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
                "controller_id": self._settings.controller_id,
                "root_id": self._settings.root_id,
                "generation": self._state.generation,
                "operator": self._state.operator,
                "terminated_writers": self._state.writers,
                "old_roles": self._settings.old_roles,
                "new_role": self._settings.new_role,
                "database": self._state.database,
            }
        )


def _stored(store: MaintenanceStore, directory: str, name: str) -> bytes | None:
    try:
        return store.read_control(directory, name)
    except FileNotFoundError:
        return None


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("controller state requires a private root-owned directory")


def _exposes(source: str, protected: Path) -> bool:
    backing = Path(source).resolve()
    if not Path(source).is_absolute() or backing != Path(os.path.normpath(source)):
        raise ValueError("mount backing path is not a trustworthy normalized identity")
    target = protected.resolve()
    return target.is_relative_to(backing) or backing.is_relative_to(target)


def _require_isolated_container(container: Container) -> None:
    configuration = container.configuration
    if configuration.privileged or "host" in (
        configuration.pid_mode,
        configuration.ipc_mode,
        configuration.network_mode,
    ):
        raise ValueError("unmanaged privileged or host-namespace container prevents exclusion")
