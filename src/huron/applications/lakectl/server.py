"""Serialized kernel-authenticated controller requests on a local Unix socket."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import socket
import socketserver
import stat
import struct
import sys
from typing import TYPE_CHECKING, cast
from uuid import UUID

from huron.core.integrity.models import FenceEvidence, ProtocolTransition

from .controller import ManagedComposeController, _private_directory
from .engine import require_local_administrator

if TYPE_CHECKING:
    from .settings import ControllerSettings


class ControllerServer(socketserver.UnixStreamServer):
    """Serialize every restart and exclusion mutation through one authoritative controller."""

    def __init__(self, settings: ControllerSettings) -> None:
        """Bind a protected socket after acquiring controller state ownership.

        Args:
            settings: Administrator-owned local deployment settings.
        """
        self.controller = ManagedComposeController(settings)
        super().__init__(str(settings.socket_path), ControllerHandler)


class ControllerHandler(socketserver.StreamRequestHandler):
    """Authenticate each request using credentials supplied by the operating system."""

    def handle(self) -> None:
        """Dispatch one bounded request without echoing credentials or configuration."""
        server = cast("ControllerServer", self.server)
        try:
            self.request.settimeout(10)
            request = _request(self.rfile.readline(65537))
            uid = _peer_uid(self.request)
            result = _dispatch(server.controller, uid, request)
            response = {"ok": True, "result": result}
        except Exception:
            response = {"ok": False, "error": "CONTROLLER_REFUSED"}
        self.wfile.write(json.dumps(response).encode() + b"\n")


def _request(raw: bytes) -> dict[str, object]:
    if len(raw) > 65536:
        raise ValueError("controller request exceeds its byte bound")
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise ValueError("controller request must be an object")
    return request


def _peer_uid(connection: socket.socket) -> int:
    option = getattr(socket, "SO_PEERCRED", None)
    if option is None:
        raise ValueError("kernel peer authentication is unavailable")
    credentials = connection.getsockopt(socket.SOL_SOCKET, option, 12)
    _, uid, _ = struct.unpack("3i", credentials)
    return int(uid)


def _dispatch(controller: ManagedComposeController, uid: int, request: dict[str, object]) -> object:
    operation = request.get("operation")
    _require_request_fields(request)
    if operation == "authenticate":
        return controller.authenticate(uid).model_dump(mode="json")
    if operation == "describe":
        return controller.describe(uid).model_dump(mode="json")
    if operation == "restart":
        return controller.restart(uid)
    if operation == "establish":
        run_id = UUID(str(request["run_id"]))
        return asyncio.run(controller.establish(uid, run_id)).model_dump(mode="json")
    if operation == "validate":
        transition = ProtocolTransition.model_validate(request["transition"])
        asyncio.run(controller.validate(uid, transition))
        return None
    evidence = FenceEvidence.model_validate(request["evidence"])
    if operation == "abandon":
        controller.abandon(uid, evidence)
    else:
        controller.check(uid, evidence)
    return None


def _require_request_fields(request: dict[str, object]) -> None:
    fields = {
        "authenticate": {"operation"},
        "describe": {"operation"},
        "restart": {"operation"},
        "establish": {"operation", "run_id"},
        "check": {"operation", "evidence"},
        "abandon": {"operation", "evidence"},
        "validate": {"operation", "transition"},
    }
    operation = request.get("operation")
    if not isinstance(operation, str) or set(request) != fields.get(operation):
        raise ValueError("unsupported controller operation or request fields")


def serve(settings: ControllerSettings) -> None:
    """Run the Linux controller while holding exclusive durable-state ownership.

    The socket accepts connections from local users, but each operation checks
    kernel peer credentials against its administrator-provisioned grant list.
    Only root can replace the socket or its parent directory.

    Args:
        settings: Authenticated administrator-provisioned deployment configuration.

    Raises:
        ValueError: If Linux peer authentication or protected socket ownership is unavailable.
    """
    require_local_administrator()
    if sys.platform != "linux":
        raise ValueError("managed exclusion requires the actual local Linux deployment")
    settings.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_directory(settings.state_path.parent)
    settings.socket_path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    parent = settings.socket_path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError("controller socket parent must be protected by root ownership")
    descriptor = os.open(
        settings.state_path.with_suffix(".lock"),
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _remove_stale_socket(settings)
        with ControllerServer(settings) as server:
            os.chmod(settings.socket_path, 0o666)
            try:
                server.serve_forever(poll_interval=0.1)
            finally:
                settings.socket_path.unlink()
    finally:
        os.close(descriptor)


def _remove_stale_socket(settings: ControllerSettings) -> None:
    try:
        info = settings.socket_path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
        raise ValueError("refusing to replace an unrelated controller socket path")
    settings.socket_path.unlink()
