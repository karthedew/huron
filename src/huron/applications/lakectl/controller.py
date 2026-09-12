"""Persistent restart admission for one private local Compose application volume."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
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
    from uuid import UUID

    from .engine import Container
    from .settings import ControllerSettings


class ManagedComposeController:
    """Own application restart authority and preserve exclusion across process restarts."""

    def __init__(self, settings: ControllerSettings) -> None:
        """Validate actual local authority and capture the isolated volume's identity.

        Args:
            settings: Private administrator-provisioned deployment configuration.
        """
        require_local_administrator()
        self._settings = settings
        self._engine = LocalEngine(settings.engine_socket)
        self._specification = settings.application_specification()
        self._image = self._engine.image_identity(str(self._specification["Image"]))
        self._volume = self._engine.volume_path(settings.volume_name)
        self._composition = hashlib.sha256(private_document(settings.compose_path)).hexdigest()
        self._state = self._load_state()
        self._certificate: str | None = None

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
        self._check_volume()
        return ControlledRoot(
            root_id=self._state.root_id,
            path=self._volume,
            owner_uid=self._settings.owner_uid,
            device=self._state.device,
            inode=self._state.inode,
        )

    def establish(self, peer_uid: int, run_id: UUID) -> FenceEvidence:
        """Persist restart exclusion before terminating all application volume holders.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            run_id: Immutable cutover attempt identity.

        Returns:
            Actual controller, volume, process-termination and restart-exclusion evidence.

        """
        grant = self.authenticate(peer_uid)
        self._certificate = None
        self._check_volume()
        writers = self._writers()
        previous = self._state.writers
        writer_ids = sorted(set(previous) | {writer.identifier for writer in writers})
        self._state = self._state.model_copy(
            update={
                "run_id": run_id,
                "operator": grant.operator,
                "writers": tuple(writer_ids),
                "generation": self._state.generation
                + int(self._state.run_id not in (None, run_id)),
            }
        )
        self._persist()
        for writer in writers:
            self._engine.terminate(writer.identifier)
        evidence = self._evidence()
        self.check(peer_uid, evidence)
        return evidence

    def check(self, peer_uid: int, evidence: FenceEvidence) -> None:
        """Verify the same live controller generation, root and persistent restart exclusion.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            evidence: Original exclusion receipt.

        Raises:
            ValueError: If the fence identity changed or any writer has appeared.
            OSError: If live storage or controller observations fail.
        """
        grant = self.authenticate(peer_uid)
        try:
            self._check_volume()
            if self._state.run_id is None or evidence != self._evidence():
                raise ValueError("controller exclusion generation changed")
            if evidence.operator != grant.operator or self._writers():
                raise ValueError("controller exclusion was lost or a foreign writer appeared")
        except (OSError, ValueError):
            self._certificate = None
            raise

    async def certify(self, peer_uid: int, transition: ProtocolTransition) -> None:
        """Endorse durable prepared evidence only after every fallible finalization step.

        Args:
            peer_uid: Kernel-authenticated maintenance operator.
            transition: Exact prepared record; its presence is not prior certification.
        """
        self.authenticate(peer_uid)
        self._certificate = None
        await self._validate_evidence(peer_uid, transition)
        self._certificate = transition.sha256

    async def validate_certificate(self, peer_uid: int, transition: ProtocolTransition) -> None:
        """Require current endorsement and fresh complete storage, SQL and controller proof.

        Args:
            peer_uid: Kernel-authenticated maintenance consumer.
            transition: Previously acknowledged or indeterminately acknowledged receipt.

        Raises:
            ValueError: If this controller has not endorsed the exact record.
        """
        self.authenticate(peer_uid)
        expected = self._certificate
        self._certificate = None
        if expected != transition.sha256:
            raise ValueError("prepared evidence has no current controller endorsement")
        await self._validate_evidence(peer_uid, transition)
        self._certificate = expected

    async def _validate_evidence(self, peer_uid: int, transition: ProtocolTransition) -> None:
        self.check(peer_uid, transition.fence)
        if transition.run_id != self._state.run_id:
            raise ValueError("certificate run differs from current controller ownership")
        store = MaintenanceStore(self._volume, self._settings.owner_uid)
        with store.claim():
            record = ProtocolTransition.decode(
                store.read_control("protocol", f"{transition.sequence:06d}.json")
            )
            if record != transition:
                raise ValueError("stored protocol record differs from presented receipt")
            inventory = ProtocolInventory.decode(
                store.read_control("protocol/reports", f"{transition.run_id}.json")
            )
            transition.validate_inventory(inventory)
            settings = MaintenanceSettings.load(self._settings.maintenance_path)
            async with asyncpg.create_pool(settings.database_url.get_secret_value()) as pool:
                await PostgresRoleExclusion(pool).check(
                    transition.fence.old_roles, transition.fence.new_role
                )
            self.check(peer_uid, transition.fence)
        self.check(peer_uid, transition.fence)

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
        info = self._volume.stat()
        try:
            state = ControllerState.model_validate_json(private_document(path))
        except FileNotFoundError:
            state = ControllerState(
                root_id=self._settings.root_id,
                controller_id=self._settings.controller_id,
                device=info.st_dev,
                inode=info.st_ino,
                composition=self._composition,
                generation=0,
            )
        self._state = state.model_copy(update={"generation": state.generation + 1})
        self._check_volume()
        self._persist()
        return self._state

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

    def _persist(self) -> None:
        path = self._settings.state_path
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(self._state.model_dump_json().encode())
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
            }
        )


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
