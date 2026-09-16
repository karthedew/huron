"""Local Compose capabilities and wiring for Integrity controller admission."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg

from huron.core.integrity import ControllerAdmission
from huron.core.integrity.models import (
    ControlledRoot,
    ControllerState,
    DeploymentObservation,
    MaintenanceGrant,
)
from huron.core.metastore.maintenance import PostgresRoleExclusion
from huron.core.rawstore.maintenance import MaintenanceStore

from .engine import LocalEngine, require_local_administrator
from .settings import MaintenanceSettings, private_document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from huron.core.integrity.ports import DatabaseExclusion

    from .engine import Container
    from .settings import ControllerSettings


def managed_controller(settings: ControllerSettings) -> ControllerAdmission:
    """Construct admission with private local capabilities and mint its start epoch.

    Args:
        settings: Private administrator-provisioned deployment configuration.

    Returns:
        Integrity's complete controller workflow, ready for serialized requests.
    """
    require_local_administrator()
    maintenance = MaintenanceSettings.load(settings.maintenance_path)
    deployment = ComposeDeployment(settings, maintenance)
    return ControllerAdmission(
        LocalOperatorAuthority(settings),
        deployment,
        FileControllerState(settings.state_path),
        MaintenanceStore(deployment.volume, settings.owner_uid),
        deployment.database,
        identity=deployment.identity,
        old_roles=settings.old_roles,
        new_role=settings.new_role,
    )


class LocalOperatorAuthority:
    """Authorize kernel-authenticated UIDs using administrator-provisioned grant lists."""

    def __init__(self, settings: ControllerSettings) -> None:
        """Bind immutable operator configuration.

        Args:
            settings: Private deployment settings loaded by the application.
        """
        self._settings = settings

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

    def require_restart(self, peer_uid: int) -> None:
        """Require the separate local application-restart grant.

        Args:
            peer_uid: UID supplied by kernel peer authentication.

        Raises:
            PermissionError: If the peer lacks restart authority.
        """
        if peer_uid not in self._settings.restart_operators:
            raise PermissionError("operator has no application restart grant")


class ComposeDeployment:
    """Observe actual Podman mounts/processes and control the fixed Compose application."""

    def __init__(self, settings: ControllerSettings, maintenance: MaintenanceSettings) -> None:
        """Resolve private deployment configuration and actual engine storage once.

        Args:
            settings: Administrator-provisioned deployment configuration.
            maintenance: Private database configuration, fixed until controller restart.
        """
        self._settings = settings
        self._maintenance = maintenance
        self._engine = LocalEngine(settings.engine_socket)
        self._specification = settings.application_specification()
        self._image = self._engine.image_identity(str(self._specification["Image"]))
        self._volume = self._engine.volume_path(settings.volume_name)
        self.identity = self._observation(self._volume).identity

    @property
    def volume(self) -> Path:
        """Return the resolved storage namespace for constructing its inspection adapter.

        Returns:
            The actual protected engine volume path.
        """
        return self._volume

    def observe(self) -> DeploymentObservation:
        """Observe volume metadata and fingerprint the current private Compose document.

        Returns:
            Validated deployment/storage identity for Integrity's persisted-state comparison.
        """
        return self._observation(self._engine.volume_path(self._settings.volume_name))

    def _observation(self, path: Path) -> DeploymentObservation:
        info = path.stat()
        return DeploymentObservation(
            root=ControlledRoot(
                root_id=self._settings.root_id,
                path=self._volume,
                owner_uid=self._settings.owner_uid,
                device=info.st_dev,
                inode=info.st_ino,
            ),
            controller_id=self._settings.controller_id,
            composition=hashlib.sha256(private_document(self._settings.compose_path)).hexdigest(),
        )

    def writers(self) -> tuple[str, ...]:
        """Inventory exact application volume holders after validating process isolation.

        Returns:
            Identities of every safely manageable writer of the protected volume.

        Raises:
            ValueError: If foreign storage, engine access or image identity defeats exclusion.
        """
        writers = []
        for container in self._engine.inventory():
            _require_isolated_container(container)
            for mount in container.mounts:
                if mount.name == self._settings.volume_name:
                    if container.image != self._image or Path(mount.source) != self._volume:
                        raise ValueError("foreign application identity holds the protected volume")
                    writers.append(container.identifier)
                elif _exposes(mount.source, self._volume) or _exposes(
                    mount.source, self._settings.engine_socket
                ):
                    raise ValueError(
                        "foreign storage or daemon access prevents complete writer inventory"
                    )
        return tuple(writers)

    def terminate(self, writer: str) -> None:
        """Ask Podman to terminate one exact observed application process.

        Args:
            writer: Immutable container identity from the validated inventory.
        """
        self._engine.terminate(writer)

    def start(self) -> str:
        """Start the fixed administrator-provisioned application through Podman.

        Returns:
            Newly created container identity.
        """
        return self._engine.start(self._specification)

    @asynccontextmanager
    async def database(self) -> AsyncIterator[DatabaseExclusion]:
        """Own a dedicated maintenance pool for one controller database observation.

        Yields:
            Role-exclusion capability bound to the private startup configuration.
        """
        async with asyncpg.create_pool(self._maintenance.database_url.get_secret_value()) as pool:
            yield PostgresRoleExclusion(pool)


class FileControllerState:
    """Read private controller state and durably replace its exact JSON document."""

    def __init__(self, path: Path) -> None:
        """Bind the exclusively owned private state-file location.

        Args:
            path: Administrator-configured state path protected by the process lock.
        """
        self._path = path

    def load(self) -> ControllerState | None:
        """Load validated state from a private root-owned directory.

        Returns:
            Persisted state or None when the state file is absent.
        """
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _private_directory(self._path.parent)
        try:
            return ControllerState.model_validate_json(private_document(self._path))
        except FileNotFoundError:
            return None

    def persist(self, state: ControllerState) -> None:
        """Replace the complete state with file and directory durability acknowledgements.

        Args:
            state: Immutable state whose exact existing JSON format must be preserved.
        """
        path = self._path
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
