"""Container engine observations fail closed at the local filesystem and HTTP boundaries."""

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from huron.applications.lakectl.engine import LocalEngine, require_local_administrator

pytestmark = pytest.mark.unit
BASE = "http://localhost/v1.41"
IDENTITY = "a" * 64


@pytest.fixture
def engine_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Model root ownership at the OS boundary while retaining real socket and mode checks."""
    original = Path.lstat

    def root_owned(path: Path) -> os.stat_result:
        values = list(original(path))
        values[4] = 0
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", root_owned)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "engine.sock"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(path.name)
        path.chmod(0o600)
        yield path


def test_engine_requires_a_private_socket(engine_socket: Path) -> None:
    """A public daemon socket and a regular file cannot authenticate the controller boundary."""
    engine_socket.chmod(0o660)
    with pytest.raises(ValueError, match="private root-owned"):
        LocalEngine(engine_socket)
    regular = engine_socket.parent / "regular"
    regular.touch(mode=0o600)
    with pytest.raises(ValueError, match="private root-owned"):
        LocalEngine(regular)


def test_administrator_identity_comes_from_the_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a root process can own the managed deployment controller."""
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    require_local_administrator()
    monkeypatch.setattr(os, "geteuid", lambda: 1001)
    with pytest.raises(PermissionError, match="root authority"):
        require_local_administrator()


@respx.mock
def test_inventory_includes_every_engine_identity_and_resolves_images(engine_socket: Path) -> None:
    """The adapter inspects all listed containers without a service label filter."""
    respx.get(f"{BASE}/containers/json", params={"all": "true"}).respond(json=[{"Id": IDENTITY}])
    respx.get(f"{BASE}/containers/{IDENTITY}/json").respond(
        json={
            "Id": IDENTITY,
            "Image": "sha256:" + IDENTITY,
            "Mounts": [
                {"Type": "volume", "Source": "/private/data", "Destination": "/data", "RW": True}
            ],
            "HostConfig": {
                "Privileged": False,
                "PidMode": "",
                "IpcMode": "private",
                "NetworkMode": "isolated",
            },
        }
    )
    respx.get(f"{BASE}/images/pinned/json").respond(json={"Id": "sha256:" + IDENTITY})
    engine = LocalEngine(engine_socket)
    observed = engine.inventory()
    assert [item.identifier for item in observed] == [IDENTITY]
    assert observed[0].mounts[0].writable
    assert engine.image_identity("pinned") == "sha256:" + IDENTITY
    respx.get(f"{BASE}/containers/json", params={"all": "true"}).respond(json=[])
    assert engine.inventory() == ()


@pytest.mark.parametrize("running", [False, True])
@respx.mock
def test_termination_removes_stopped_and_running_identities(
    engine_socket: Path, running: bool
) -> None:
    """Termination removes restartable identities only after observing no live process."""
    states = [{"State": {"Running": running, "Pid": 12 if running else 0}}]
    if running:
        states.append({"State": {"Running": False, "Pid": 0}})
        respx.post(f"{BASE}/containers/{IDENTITY}/stop", params={"t": "10"}).respond(204)
    respx.get(f"{BASE}/containers/{IDENTITY}/json").mock(
        side_effect=[httpx.Response(200, json=item) for item in states]
    )
    removal = respx.delete(
        f"{BASE}/containers/{IDENTITY}", params={"v": "false", "force": "false"}
    ).respond(204)
    LocalEngine(engine_socket).terminate(IDENTITY)
    assert removal.called


@pytest.mark.parametrize("running,pid", [(True, 12), (False, 12)])
@respx.mock
def test_live_process_evidence_refuses_removal(
    engine_socket: Path, running: bool, pid: int
) -> None:
    """A stop response cannot override an engine observation of a surviving writer."""
    respx.get(f"{BASE}/containers/{IDENTITY}/json").respond(
        json={"State": {"Running": running, "Pid": pid}}
    )
    if running:
        respx.post(f"{BASE}/containers/{IDENTITY}/stop", params={"t": "10"}).respond(204)
    with pytest.raises(ValueError, match="termination was not confirmed"):
        LocalEngine(engine_socket).terminate(IDENTITY)


@pytest.mark.parametrize("failure", [False, True])
@respx.mock
def test_startup_failure_removes_the_created_identity(engine_socket: Path, failure: bool) -> None:
    """An unsuccessful launch leaves no stopped container available for an uncontrolled restart."""
    respx.post(f"{BASE}/containers/create").respond(201, json={"Id": IDENTITY})
    respx.post(f"{BASE}/containers/{IDENTITY}/start").respond(500 if failure else 204)
    engine = LocalEngine(engine_socket)
    if failure:
        respx.get(f"{BASE}/containers/{IDENTITY}/json").respond(
            json={"State": {"Running": False, "Pid": 0}}
        )
        removal = respx.delete(
            f"{BASE}/containers/{IDENTITY}", params={"v": "false", "force": "false"}
        ).respond(204)
        with pytest.raises(httpx.HTTPStatusError):
            engine.start({"Image": "pinned"})
        assert removal.called
    else:
        assert engine.start({"Image": "pinned"}) == IDENTITY


@pytest.mark.parametrize(
    "case", ["valid", "remote", "options", "scope", "public", "escape", "missing", "symlink"]
)
@respx.mock
def test_volume_requires_actual_private_local_storage(engine_socket: Path, case: str) -> None:
    """Remote, exposed, absent and redirected volume storage cannot support a local fence."""
    root = engine_socket.parent / "storage"
    root.mkdir(mode=0o700)
    mount = root / "data"
    mount.mkdir()
    volume = {"Driver": "local", "Options": None, "Scope": "local", "Mountpoint": str(mount)}
    if case in {"remote", "options", "scope"}:
        field = {"remote": "Driver", "options": "Options", "scope": "Scope"}[case]
        volume[field] = "unsupported"
    if case == "public":
        root.chmod(0o755)
    if case == "escape":
        volume["Mountpoint"] = str(root.parent)
    if case == "missing":
        mount.rmdir()
    if case == "symlink":
        mount.rmdir()
        mount.symlink_to(root.parent, target_is_directory=True)
    respx.get(f"{BASE}/volumes/raw").respond(json=volume)
    if case not in {"remote", "options", "scope"}:
        respx.get(f"{BASE}/info").respond(json={"DockerRootDir": str(root)})
    if case == "valid":
        assert LocalEngine(engine_socket).volume_path("raw") == mount
    else:
        with pytest.raises(ValueError):
            LocalEngine(engine_socket).volume_path("raw")
