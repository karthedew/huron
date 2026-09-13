"""Unix-socket clients for kernel-authenticated controller authority and exclusion."""

from __future__ import annotations

import json
import socket
import stat
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.core.integrity.models import FenceEvidence, MaintenanceGrant, ProtocolTransition

from .settings import ControlledRoot

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID


class ControllerClient:
    """Use live controller decisions instead of caller-supplied maintenance assertions."""

    def __init__(self, socket_path: Path) -> None:
        """Bind the controller's administrator-owned socket.

        Args:
            socket_path: Local controller socket protected against replacement.
        """
        self._socket_path = socket_path

    async def authenticate(self) -> MaintenanceGrant:
        """Authenticate using peer credentials observed by the controller's kernel.

        Returns:
            The controller's live operation and root grant.
        """
        return MaintenanceGrant.model_validate(
            await asyncify(self._call)({"operation": "authenticate"})
        )

    async def describe(self) -> ControlledRoot:
        """Obtain the authenticated controller's actual local storage identity.

        Returns:
            Root identity for constructing the inspection adapter.
        """
        return ControlledRoot.model_validate(await asyncify(self._call)({"operation": "describe"}))

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Acquire externally enforced shutdown and restart exclusion.

        Args:
            grant: Prior authenticated grant checked against the controller response.
            run_id: Immutable cutover run identity.

        Returns:
            Live controller evidence after actual process termination.

        Raises:
            PermissionError: If the controller's authenticated identity changed.
        """
        result = await asyncify(self._call)({"operation": "establish", "run_id": str(run_id)})
        evidence = FenceEvidence.model_validate(result)
        if (grant.root_id, grant.operator) != (evidence.root_id, evidence.operator):
            raise PermissionError("controller authentication changed during exclusion")
        return evidence

    async def check(self, evidence: FenceEvidence) -> None:
        """Require a fresh live proof of the same continuously enforced exclusion.

        Args:
            evidence: Original controller evidence for this verification interval.
        """
        await asyncify(self._call)(
            {
                "operation": "check",
                "evidence": evidence.model_dump(mode="json"),
            }
        )

    async def abandon(self, evidence: FenceEvidence) -> None:
        """Declare that this receipt's run did not complete, ending its epoch.

        Args:
            evidence: Receipt whose continuous observation failed or whose run did not return.
        """
        await asyncify(self._call)(
            {"operation": "abandon", "evidence": evidence.model_dump(mode="json")}
        )

    async def validate(self, transition: ProtocolTransition) -> None:
        """Ask the controller to admit a stored record under the live epoch.

        Args:
            transition: Record exactly as stored under ``protocol/{sequence:06d}.json``.
        """
        await asyncify(self._call)(
            {
                "operation": "validate",
                "transition": transition.model_dump(mode="json", by_alias=True),
            }
        )

    async def restart(self) -> str:
        """Request the controller's fixed application start through its admission policy.

        Returns:
            Actual started container identity.
        """
        return str(await asyncify(self._call)({"operation": "restart"}))

    def _call(self, request: dict[str, object]) -> object:
        info = self._socket_path.lstat()
        parent = self._socket_path.parent.stat()
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != 0
            or parent.st_uid != 0
            or parent.st_mode & 0o022
        ):
            raise PermissionError("controller socket is not protected by administrator ownership")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(60)
            connection.connect(str(self._socket_path))
            connection.sendall(json.dumps(request).encode() + b"\n")
            with connection.makefile("rb") as response:
                return _reply(response.readline(65537))


def _reply(payload: bytes) -> object:
    """Map one bounded response line to its result or the failure it represents.

    Args:
        payload: Raw bytes read from the controller's response line, bound-limited.

    Returns:
        The reply's ``result`` field.

    Raises:
        ValueError: If the payload exceeds its bound or is not a reply object.
        ConnectionError: If the connection closed before a complete reply arrived.
        PermissionError: If the controller refused the requested operation.
    """
    if len(payload) > 65536:
        raise ValueError("controller response exceeds its bound")
    if not payload.endswith(b"\n"):
        raise ConnectionError("controller closed the connection without a reply")
    reply = json.loads(payload)
    if not isinstance(reply, dict) or "ok" not in reply:
        raise ValueError("controller reply is not a reply object")
    if not reply["ok"]:
        raise PermissionError("controller refused the requested maintenance operation")
    return reply.get("result")
