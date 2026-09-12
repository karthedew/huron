"""Real Unix transport preserves request bounds, authority mapping and safe error responses."""

import json
import socket
import struct
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

from huron.applications.lakectl.exclusion import ControllerClient
from huron.applications.lakectl.server import ControllerServer, serve
from huron.applications.lakectl.settings import ControllerSettings
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_managed_controller import EngineBoundary
from tests.unit.test_managed_controller import engine_boundary as engine_boundary

pytestmark = pytest.mark.unit


@pytest.fixture
def transport_settings(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ControllerSettings:
    """Use short real Unix paths and inject only kernel peer credentials unavailable on macOS."""
    monkeypatch.chdir(tmp_path)
    original = socket.socket.getsockopt
    option = getattr(socket, "SO_PEERCRED", 10000)

    def credentials(connection: socket.socket, level: int, name: int, size: int = 0) -> bytes | int:
        if name == option:
            return struct.pack("3i", 1, 1002, 1002)
        if size:
            return original(connection, level, name, size)
        return original(connection, level, name)

    monkeypatch.setattr(socket, "SO_PEERCRED", option, raising=False)
    monkeypatch.setattr(socket.socket, "getsockopt", credentials)
    return controller_settings.model_copy(update={"socket_path": Path("controller.sock")})


@pytest.fixture
def live_server(transport_settings: ControllerSettings) -> Iterator[ControllerServer]:
    """Serve actual serialized controller requests over an owned Unix socket."""
    with ControllerServer(transport_settings) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)
            transport_settings.socket_path.unlink(missing_ok=True)


async def test_client_authenticates_describes_establishes_and_checks_real_requests(
    transport_settings: ControllerSettings,
    live_server: ControllerServer,
) -> None:
    """The wire carries controller grants and exclusion receipts without accepting actor text."""
    client = ControllerClient(transport_settings.socket_path)
    grant = await client.authenticate()
    assert grant.operator == "local:1002"
    root = await client.describe()
    assert root.root_id == grant.root_id
    evidence = await client.establish(grant, UUID(int=3))
    await client.check(evidence)
    with pytest.raises(PermissionError, match="refused"):
        await client.restart()
    with pytest.raises(PermissionError, match="authentication changed"):
        await client.establish(grant.model_copy(update={"operator": "forged"}), UUID(int=3))


async def test_restart_response_returns_the_real_admitted_identity(
    transport_settings: ControllerSettings,
) -> None:
    """A peer with restart authority receives the engine identity through the same transport."""
    settings = transport_settings.model_copy(update={"restart_operators": (1002,)})
    with ControllerServer(settings) as server:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            assert await ControllerClient(settings.socket_path).restart() == "b" * 64
        finally:
            thread.join(timeout=2)
            settings.socket_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "payload",
    [
        b"[]\n",
        b"x\n",
        b"x" * 65537,
        b'{"operation":"authenticate","actor":"root"}\n',
        b'{"operation":"unknown"}\n',
    ],
)
def test_server_refuses_malformed_oversized_and_actor_supplied_requests(
    transport_settings: ControllerSettings,
    live_server: ControllerServer,
    payload: bytes,
) -> None:
    """Unrecognized wire input returns only a generic refusal with no configuration leakage."""
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(transport_settings.socket_path))
        connection.sendall(payload)
        with connection.makefile("rb") as response:
            assert json.loads(response.readline()) == {"ok": False, "error": "CONTROLLER_REFUSED"}


async def test_missing_kernel_peer_authentication_fails_closed(
    transport_settings: ControllerSettings,
    live_server: ControllerServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable kernel credential interface cannot fall back to asserted actor identity."""
    monkeypatch.delattr(socket, "SO_PEERCRED")
    with pytest.raises(PermissionError, match="refused"):
        await ControllerClient(transport_settings.socket_path).authenticate()


async def test_client_refuses_replaceable_socket_and_oversized_response(
    transport_settings: ControllerSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client authority depends on protected socket metadata and bounded server responses."""
    path = transport_settings.socket_path
    path.touch()
    with pytest.raises(PermissionError, match="ownership"):
        await ControllerClient(path).authenticate()
    path.unlink()
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen()

        def oversized_response() -> None:
            with listener.accept()[0] as connection:
                connection.recv(4096)
                connection.sendall(b"x" * 65537)

        thread = threading.Thread(target=oversized_response)
        thread.start()
        try:
            with pytest.raises(ValueError, match="response exceeds"):
                await ControllerClient(path).authenticate()
        finally:
            thread.join(timeout=2)
            path.unlink()


def test_server_requires_linux_and_a_protected_socket_parent(
    transport_settings: ControllerSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported platforms and replaceable socket parents cannot host authoritative admission."""
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ValueError, match="actual local Linux"):
        serve(transport_settings)
    monkeypatch.setattr(sys, "platform", "linux")
    Path.cwd().chmod(0o777)
    try:
        with pytest.raises(ValueError, match="socket parent"):
            serve(transport_settings)
    finally:
        Path.cwd().chmod(0o700)


@pytest.mark.parametrize("stale", [False, True, "unrelated"])
def test_server_owns_state_lock_and_cleans_its_socket_on_shutdown(
    transport_settings: ControllerSettings,
    monkeypatch: pytest.MonkeyPatch,
    stale: bool | str,
) -> None:
    """Lifecycle removes only an owned stale socket and cleans up after a serving failure."""
    monkeypatch.setattr(sys, "platform", "linux")
    path = transport_settings.socket_path
    if stale == "unrelated":
        path.touch()
    elif stale:
        with socket.socket(socket.AF_UNIX) as previous:
            previous.bind(str(path))

    def interrupted(server: ControllerServer, poll_interval: float) -> None:
        raise OSError("serving interrupted")

    monkeypatch.setattr(ControllerServer, "serve_forever", interrupted)
    if stale == "unrelated":
        with pytest.raises(ValueError, match="unrelated"):
            serve(transport_settings)
        assert path.is_file()
    else:
        with pytest.raises(OSError, match="interrupted"):
            serve(transport_settings)
        assert not path.exists()


async def test_real_transport_endorses_and_validates_exact_durable_evidence(
    transport_settings: ControllerSettings, live_server: ControllerServer,
    engine_boundary: EngineBoundary, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete RPC path validates stored bindings and current SQL exclusion."""
    from datetime import UTC, datetime
    from huron.applications.lakectl import controller as controller_module
    from huron.core.integrity.models import ProtocolInventory, ProtocolTransition
    from huron.pkg.rawstore.maintenance import MaintenanceStore
    from tests.unit.test_lakectl_wiring import EmptyDatabaseBoundary

    monkeypatch.setattr(controller_module.asyncpg, "create_pool", lambda url: EmptyDatabaseBoundary())
    client = ControllerClient(transport_settings.socket_path)
    grant = await client.authenticate()
    fence = await client.establish(grant, UUID(int=3))
    inventory = ProtocolInventory(root_id=grant.root_id, run_id=UUID(int=3), fence=fence, revisions=())
    record = ProtocolTransition.bind(inventory, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC),
                                    code_digest="b" * 64)
    store = MaintenanceStore(engine_boundary.volume, 1001)
    store.write_evidence(record.report_path, inventory.canonical)
    store.write_evidence("000001.json", record.canonical)
    with pytest.raises(PermissionError, match="refused"):
        await client.validate_certificate(record)
    await client.certify(record)
    await client.validate_certificate(record)
    with pytest.raises(PermissionError, match="refused"):
        await client.certify(record.model_copy(update={"run_id": UUID(int=4)}))
    with pytest.raises(PermissionError, match="refused"):
        await client.validate_certificate(record)


async def test_lost_endorsement_reply_is_indeterminate_and_live_validation_resolves_it(
    transport_settings: ControllerSettings, live_server: ControllerServer,
    engine_boundary: EngineBoundary, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped acknowledgement does not turn truly endorsed evidence into a claimed failure."""
    from datetime import UTC, datetime
    import socketserver
    from huron.applications.lakectl import controller as controller_module
    from huron.core.integrity.models import CertificationIndeterminateError, ProtocolInventory, ProtocolTransition
    from huron.pkg.rawstore.maintenance import MaintenanceStore
    from tests.unit.test_lakectl_wiring import EmptyDatabaseBoundary

    monkeypatch.setattr(controller_module.asyncpg, "create_pool", lambda url: EmptyDatabaseBoundary())
    client = ControllerClient(transport_settings.socket_path)
    grant = await client.authenticate()
    fence = await client.establish(grant, UUID(int=3))
    inventory = ProtocolInventory(root_id=grant.root_id, run_id=UUID(int=3), fence=fence, revisions=())
    record = ProtocolTransition.bind(inventory, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC),
                                    code_digest="b" * 64)
    store = MaintenanceStore(engine_boundary.volume, 1001)
    store.write_evidence(record.report_path, inventory.canonical)
    store.write_evidence("000001.json", record.canonical)

    def dropped(stream: object, payload: bytes) -> int:
        return len(payload)

    with monkeypatch.context() as patch:
        patch.setattr(socketserver._SocketWriter, "write", dropped)
        with pytest.raises(CertificationIndeterminateError, match="indeterminate"):
            await client.certify(record)
    await client.validate_certificate(record)
