"""Unix-socket clients for kernel-authenticated controller authority and exclusion."""

from __future__ import annotations

import asyncio
import json
import socket
import stat
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.core.integrity.models import (
    CertificationIndeterminateError,
    FenceEvidence,
    MaintenanceGrant,
    ProtocolTransition,
)

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

    async def certify(self, transition: ProtocolTransition) -> None:
        """Request endorsement, distinguishing an uncertain acknowledgement from rejection.

        Args:
            transition: Complete immutable prepared evidence.

        Raises:
            CertificationIndeterminateError: If the authority's reply is lost or unreadable.
            PermissionError: If the authority definitively refuses the request.
        """
        try:
            await asyncify(self._call)(
                {
                    "operation": "certify",
                    "transition": transition.model_dump(mode="json", by_alias=True),
                }
            )
        except PermissionError:
            raise
        except (OSError, ValueError, asyncio.CancelledError) as exc:
            raise CertificationIndeterminateError(
                "certificate acknowledgement is indeterminate"
            ) from exc

    async def validate_certificate(self, transition: ProtocolTransition) -> None:
        """Ask the authority to validate exact evidence and current exclusion for a consumer.

        Args:
            transition: Receipt whose current endorsement must be checked.
        """
        await asyncify(self._call)(
            {
                "operation": "validate_certificate",
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
                payload = response.readline(65537)
        if len(payload) > 65536:
            raise ValueError("controller response exceeds its bound")
        result = json.loads(payload)
        if not result["ok"]:
            raise PermissionError("controller refused the requested maintenance operation")
        return result["result"]
