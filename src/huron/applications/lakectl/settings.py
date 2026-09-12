"""Strict root-controlled configuration for a local managed Compose deployment."""

import json
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ControllerState(BaseModel):
    """Durable restart admission bound to a particular root and controller generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root_id: UUID
    controller_id: UUID
    device: int
    inode: int
    composition: str
    generation: Annotated[int, Field(ge=0)]
    run_id: UUID | None = None
    writers: tuple[str, ...] = ()
    operator: str | None = None


class ControlledRoot(BaseModel):
    """Live storage identity supplied by the authenticated deployment controller."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root_id: UUID
    path: Path
    owner_uid: Annotated[int, Field(ge=1)]
    device: int
    inode: int


class MaintenanceSettings(BaseModel):
    """Private connection material for the dedicated cutover database identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    controller_socket: Path
    database_url: SecretStr

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read administrator-controlled maintenance connection configuration.

        Args:
            path: Private root-owned configuration file.

        Returns:
            Validated settings with secret-safe representation.
        """
        return cls.model_validate_json(private_document(path))


class ControllerSettings(BaseModel):
    """Administrator-provisioned authority and immutable deployment configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root_id: UUID
    controller_id: UUID
    engine_socket: Path
    socket_path: Path
    state_path: Path
    compose_path: Path
    maintenance_path: Path
    volume_name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")]
    owner_uid: Annotated[int, Field(ge=1)]
    cutover_operators: tuple[int, ...]
    restart_operators: tuple[int, ...]
    old_roles: tuple[str, ...]
    new_role: str

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read only administrator-owned, private configuration.

        Args:
            path: Private root-owned configuration file.

        Returns:
            Validated immutable settings.
        """
        return cls.model_validate_json(private_document(path))

    def application_specification(self) -> dict[str, object]:
        """Translate the supported resolved Compose API service into an engine request.

        Only the fixed service configuration is admitted. Container creation never
        accepts a caller-supplied image, environment, mounts or command.

        Returns:
            A nonprivileged application container specification with one named volume.

        Raises:
            ValueError: If Compose requests any unsupported or unsafe deployment feature.
        """
        compose = json.loads(private_document(self.compose_path))
        service = compose["services"]["api"]
        allowed = {"image", "command", "environment", "user", "volumes", "networks"}
        if set(service) - allowed or service["user"] != str(self.owner_uid):
            raise ValueError("managed Compose service contains unsupported configuration")
        image = str(service["image"])
        if not re.fullmatch(r"(?:sha256:|[^\s@]+@sha256:)[0-9a-f]{64}", image):
            raise ValueError("managed Compose requires an immutable application image digest")
        volume = [{"type": "volume", "source": self.volume_name, "target": "/data"}]
        if service["volumes"] != volume or len(service["networks"]) != 1:
            raise ValueError("managed Compose requires one isolated volume and network")
        return {
            "Image": image,
            "User": str(self.owner_uid),
            "Cmd": service["command"],
            "Env": [f"{key}={value}" for key, value in sorted(service["environment"].items())],
            "Labels": {
                "com.docker.compose.project": compose["name"],
                "com.docker.compose.service": "api",
            },
            "HostConfig": {
                "NetworkMode": service["networks"][0],
                "RestartPolicy": {"Name": "no"},
                "Mounts": [{"Type": "volume", "Source": self.volume_name, "Target": "/data"}],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
            },
        }


def private_document(path: Path) -> bytes:
    """Read a private regular root-owned configuration without following symlinks.

    Args:
        path: Administrator-provisioned file.

    Returns:
        Exact configuration bytes, never emitted as operator evidence.

    Raises:
        ValueError: If the configuration is not private and administrator-owned.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("controller configuration must be a private root-owned regular file")
        _protected_ancestors(path.absolute().parent)
        payload = source.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("controller configuration exceeds its byte bound")
        return payload


def _protected_ancestors(path: Path) -> None:
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("controller configuration ancestors must be protected by root")
