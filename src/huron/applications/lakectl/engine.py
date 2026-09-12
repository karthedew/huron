"""Local container-engine observations and confirmed writer removal."""

import os
import stat
from pathlib import Path
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field


class Mount(BaseModel):
    """Required mount facts returned by container inspection."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    kind: str = Field(alias="Type")
    source: str = Field(alias="Source")
    destination: str = Field(alias="Destination")
    writable: bool = Field(alias="RW")
    name: str | None = Field(default=None, alias="Name")


class ContainerConfiguration(BaseModel):
    """Required identity and privilege facts for a possible writer."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    privileged: bool = Field(alias="Privileged")
    pid_mode: str = Field(alias="PidMode")
    ipc_mode: str = Field(alias="IpcMode")
    network_mode: str = Field(alias="NetworkMode")


class Container(BaseModel):
    """An immutable engine observation, never an assertion supplied by an operator."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    identifier: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] = Field(alias="Id")
    image: str = Field(alias="Image")
    mounts: tuple[Mount, ...] = Field(alias="Mounts")
    configuration: ContainerConfiguration = Field(alias="HostConfig")


class LocalEngine:
    """Inspect the entire local daemon and remove writers through its authenticated socket."""

    def __init__(self, socket_path: Path) -> None:
        """Require a root-owned private Unix socket before connecting to the daemon.

        Args:
            socket_path: Local root-owned engine socket inaccessible to application users.

        Raises:
            ValueError: If the socket is not exclusively controlled by root.
        """
        info = socket_path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("container engine requires a private root-owned Unix socket")
        self._socket = socket_path

    def _request(
        self, method: str, path: str, document: dict[str, object] | None = None
    ) -> httpx.Response:
        transport = httpx.HTTPTransport(uds=str(self._socket))
        with httpx.Client(transport=transport, base_url="http://localhost", timeout=30) as client:
            response = client.request(method, f"/v1.41{path}", json=document)
            response.raise_for_status()
            return response

    def inventory(self) -> tuple[Container, ...]:
        """Inspect all stopped and running containers, without label-based omissions.

        Returns:
            Complete daemon-wide container observations.
        """
        summaries = self._request("GET", "/containers/json?all=true").json()
        return tuple(
            Container.model_validate(self._request("GET", f"/containers/{item['Id']}/json").json())
            for item in summaries
        )

    def volume_path(self, volume_name: str) -> Path:
        """Verify a local named volume lives behind a private root-owned storage directory.

        Args:
            volume_name: Controller-configured named volume.

        Returns:
            Local backing path whose identity and permissions were checked.

        Raises:
            ValueError: If the volume is remote or accessible to unmanaged host writers.
        """
        volume = self._request("GET", f"/volumes/{volume_name}").json()
        if volume["Driver"] != "local" or volume.get("Options") or volume["Scope"] != "local":
            raise ValueError("only isolated local named volumes support this controller")
        root = Path(self._request("GET", "/info").json()["DockerRootDir"])
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("host applications can access the engine's storage root")
        path = Path(volume["Mountpoint"])
        if not path.is_relative_to(root) or path.resolve() != path or not path.is_dir():
            raise ValueError("named volume escapes the isolated engine storage root")
        return path

    def terminate(self, container_id: str) -> None:
        """Stop the container, confirm termination and remove its restartable identity.

        Args:
            container_id: Exact identity obtained from complete engine inspection.

        Raises:
            ValueError: If the engine still reports a running process.
        """
        status = self._request("GET", f"/containers/{container_id}/json").json()["State"]
        if status["Running"]:
            self._request("POST", f"/containers/{container_id}/stop?t=10")
            status = self._request("GET", f"/containers/{container_id}/json").json()["State"]
        if status["Running"] or status["Pid"] != 0:
            raise ValueError("writer process termination was not confirmed")
        self._request("DELETE", f"/containers/{container_id}?v=false&force=false")

    def start(self, specification: dict[str, object]) -> str:
        """Create and start the controller's fixed application specification.

        Args:
            specification: Validated deployment configuration, never request-supplied code.

        Returns:
            The real immutable engine container identity.

        Raises:
            httpx.HTTPError: If startup fails after removal of the created identity is attempted.
        """
        identifier = str(self._request("POST", "/containers/create", specification).json()["Id"])
        try:
            self._request("POST", f"/containers/{identifier}/start")
        except httpx.HTTPError:
            self.terminate(identifier)
            raise
        return identifier

    def image_identity(self, reference: str) -> str:
        """Resolve a pinned image reference to the engine's actual image identity.

        Args:
            reference: Immutable configured image reference.

        Returns:
            Image content identity used for comparison with inspected containers.
        """
        return str(self._request("GET", f"/images/{reference}/json").json()["Id"])


def require_local_administrator() -> None:
    """Require real local root authority for the container-controller process.

    Raises:
        PermissionError: If the controller lacks authenticated operating-system authority.
    """
    if os.geteuid() != 0:
        raise PermissionError("the deployment controller requires local root authority")
