"""Disposable Linux deployment exercising an immutable historical application artifact."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def provision(
    checkout: pathlib.Path, requirements: pathlib.Path, legacy_archive: pathlib.Path
) -> None:
    """Build and exercise one private engine, cleaning every owned resource afterward.

    Args:
        checkout: Source checkout exposed read-only to the fixture runtime.
        requirements: Locked runtime requirement export.
        legacy_archive: Digest-verified historical application source archive.
    """
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("the controlled deployment fixture requires local Linux root")

    def interrupted(signum: int, frame: object) -> None:
        raise InterruptedError("owned deployment fixture interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    root = pathlib.Path(tempfile.mkdtemp(prefix="huron-controlled-test-", dir="/var/lib"))
    service = None
    command = [
        "podman",
        "--root",
        str(root / "storage"),
        "--runroot",
        str(root / "run"),
        "--network-config-dir",
        str(root / "networks"),
    ]
    try:
        print("ROOT", root, flush=True)
        subprocess.run(["python3", "-m", "venv", str(root / "venv")], check=True)
        shutil.copyfile(requirements, root / "requirements.txt")
        subprocess.run(
            [str(root / "venv/bin/pip"), "install", "-r", str(root / "requirements.txt")],
            check=True,
        )
        shutil.copytree(checkout / "src", root / "src")
        os.environ["PYTHONPATH"] = str(root / "src")
        (root / "storage").mkdir(mode=0o700)
        if pathlib.Path("/sys/fs/selinux/enforce").exists():
            context = subprocess.check_output(
                ["matchpathcon", "-n", "/var/lib/containers/storage"], text=True
            ).strip()
            subprocess.run(["chcon", context, str(root / "storage")], check=True)
        os.umask(0o077)
        service = subprocess.Popen(
            [*command, "system", "service", "--time", "0", "unix://" + str(root / "engine.sock")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for _ in range(100):
            if (root / "engine.sock").exists():
                break
            if service.poll() is not None:
                raise RuntimeError(service.stderr.read().decode())
            time.sleep(0.1)
        import tarfile

        (root / "legacy").mkdir()
        with tarfile.open(legacy_archive) as archive:
            archive.extractall(root / "legacy", filter="data")
        containerfile = root / "legacy/Containerfile"
        containerfile.write_text(
            containerfile.read_text().replace(
                "COPY pyproject.toml uv.lock ./", "COPY pyproject.toml uv.lock README.md ./"
            )
        )
        subprocess.run(
            [
                *command,
                "build",
                "--iidfile",
                str(root / "image-id"),
                "--file",
                str(root / "legacy/Containerfile"),
                str(root / "legacy"),
            ],
            check=True,
        )
        image = (root / "image-id").read_text().strip()
        print("LEGACY_IMAGE", image, flush=True)
        subprocess.run([*command, "volume", "create", "huron-proof"], check=True)
        subprocess.run([*command, "network", "create", "huron-proof"], check=True)
        volume = pathlib.Path(
            json.loads(subprocess.check_output([*command, "volume", "inspect", "huron-proof"]))[0][
                "Mountpoint"
            ]
        )
        os.chown(volume, 1001, 1001)
        subprocess.run(
            ["ls", "-Zd", str(root / "storage"), str(root / "storage/overlay")], check=True
        )
        image = "sha256:" + image.removeprefix("sha256:")
        subprocess.run(
            [
                *command,
                "run",
                "-d",
                "--name",
                "postgres",
                "--network",
                "huron-proof",
                "-e",
                "POSTGRES_USER=owner",
                "-e",
                "POSTGRES_PASSWORD=fixture-password",
                "-e",
                "POSTGRES_DB=huron",
                "docker.io/library/postgres:16",
            ],
            check=True,
        )
        for _ in range(100):
            if (
                subprocess.run(
                    [*command, "exec", "postgres", "pg_isready", "-U", "owner", "-d", "huron"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.2)
        subprocess.run(
            [
                *command,
                "run",
                "--rm",
                "--network",
                "huron-proof",
                "-e",
                "HURON_DATABASE_URL=postgresql://owner:fixture-password@postgres/huron",
                image,
                "alembic",
                "upgrade",
                "head",
            ],
            check=True,
        )
        sql = (
            "CREATE ROLE old_app LOGIN PASSWORD 'fixture-password'; "
            "CREATE ROLE new_app LOGIN PASSWORD 'replacement-password'; "
            "CREATE ROLE cutover LOGIN SUPERUSER PASSWORD 'maintenance-password'; "
            "GRANT USAGE ON SCHEMA public TO old_app; "
            "GRANT ALL ON ALL TABLES IN SCHEMA public TO old_app; "
            "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO old_app;"
        )
        subprocess.run(
            [*command, "exec", "postgres", "psql", "-U", "owner", "-d", "huron", "-c", sql],
            check=True,
        )
        environment = {
            "HURON_ENV": "development",
            "HURON_AUTH_MODE": "dev-headers",
            "HURON_DATABASE_URL": "postgresql://old_app:fixture-password@postgres/huron",
            "HURON_DATA_ROOT": "/data",
            "HURON_BOOTSTRAP_PLATFORM_OWNER": "root",
            "HURON_CLASSIFICATION_VOCABULARY": '[{"code":"open","order":0,"discoverable":true}]',
        }
        compose = {
            "name": "huron-proof",
            "services": {
                "api": {
                    "image": image,
                    "user": "1001",
                    "command": [
                        "uvicorn",
                        "huron.applications.api.main:app",
                        "--host",
                        "0.0.0.0",
                        "--port",
                        "8080",
                    ],
                    "environment": environment,
                    "volumes": [{"type": "volume", "source": "huron-proof", "target": "/data"}],
                    "networks": ["huron-proof"],
                }
            },
        }
        (root / "compose.json").write_text(json.dumps(compose))
        settings = {
            "root_id": str(uuid.uuid4()),
            "controller_id": str(uuid.uuid4()),
            "engine_socket": str(root / "engine.sock"),
            "socket_path": str(root / "controller.sock"),
            "state_path": str(root / "state.json"),
            "compose_path": str(root / "compose.json"),
            "maintenance_path": str(root / "maintenance.json"),
            "volume_name": "huron-proof",
            "owner_uid": 1001,
            "cutover_operators": [0],
            "restart_operators": [0],
            "old_roles": ["old_app"],
            "new_role": "new_app",
        }
        postgres = json.loads(subprocess.check_output([*command, "inspect", "postgres"]))[0]
        database_address = postgres["NetworkSettings"]["Networks"]["huron-proof"]["IPAddress"]
        (root / "maintenance.json").write_text(json.dumps({
            "controller_socket": str(root / "controller.sock"),
            "database_url": f"postgresql://cutover:maintenance-password@{database_address}/huron",
        }))
        (root / "maintenance.json").chmod(0o600)
        (root / "settings.json").write_text(json.dumps(settings))
        subprocess.run(
            [
                str(root / "venv/bin/python"),
                str(checkout / "tests/controlled_deployment.py"),
                "scenario",
                str(root),
            ],
            check=True,
            env=os.environ,
        )
    finally:
        subprocess.run([*command, "rm", "--all", "--force"], check=False)
        if service is not None:
            service.terminate()
            try:
                service.wait(timeout=20)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait(timeout=20)
        subprocess.run([*command, "volume", "rm", "--all", "--force"], check=False)
        subprocess.run([*command, "network", "rm", "huron-proof"], check=False)
        subprocess.run([*command, "rmi", "--all", "--force"], check=False)
        shutil.rmtree(root)
        print("CLEANED", root, flush=True)


def scenario(root: pathlib.Path) -> None:
    """Prove an actual historical HTTP writer is terminated independently of SQL fencing.

    Args:
        root: Owned private fixture state and engine directory.
    """
    import asyncio
    import json
    import subprocess
    import time
    import uuid

    import asyncpg

    from huron.applications.lakectl.controller import ManagedComposeController
    from huron.applications.lakectl.settings import ControllerSettings
    from huron.pkg.metastore.maintenance import PostgresRoleExclusion

    engine = [
        "podman",
        "--root",
        str(root / "storage"),
        "--runroot",
        str(root / "run"),
        "--network-config-dir",
        str(root / "networks"),
    ]
    controller = ManagedComposeController(ControllerSettings.load(root / "settings.json"))
    writer = controller.restart(0)
    volume = controller.describe(0).path
    ready = "import urllib.request; assert urllib.request.urlopen('http://localhost:8080/readyz').status==200"
    for _ in range(100):
        if (
            subprocess.run(
                [*engine, "exec", writer, "python", "-c", ready],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        ):
            break
        time.sleep(0.2)
    else:
        subprocess.run([*engine, "logs", writer])
        raise AssertionError("legacy artifact never became ready before fencing")
    print("LEGACY_READY", writer, flush=True)
    import hashlib
    import socket

    import httpx

    application = json.loads(subprocess.check_output([*engine, "inspect", writer]))[0]
    address = application["NetworkSettings"]["Networks"]["huron-proof"]["IPAddress"]
    client = httpx.Client(
        base_url=f"http://{address}:8080/api/v1", headers={"X-Huron-Subject": "root"}, timeout=15
    )

    def create(path, body):
        """Exercise an authorized legacy API creation operation."""
        response = client.post(path, json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
        assert response.status_code == 201, (response.status_code, response.text)
        return response.json()

    organization = create("/organizations", {"slug": "proof-org", "title": "Proof"})
    project = create(
        "/organizations/" + organization["id"] + "/projects",
        {"slug": "proof-project", "title": "Proof", "data_classification": "open"},
    )
    create(
        "/projects/" + project["id"] + "/bindings", {"principal": "user:root", "role": "developer"}
    )
    dataset = create(
        "/projects/" + project["id"] + "/datasets",
        {
            "slug": "proof-dataset",
            "title": "Proof",
            "profile_name": "mcnp-run",
            "profile_version": "1.0",
        },
    )
    content = b"x" * (1 << 20)
    ledger = create(
        "/datasets/" + dataset["id"] + "/ingest-sessions",
        {
            "files": [
                {
                    "path": "payload/file",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ]
        },
    )
    file_id = ledger["files"][0]["file_id"]
    connection = socket.create_connection((address, 8080), timeout=15)
    headers = (
        f"PUT /api/v1/transfer/uploads/{file_id}/parts/1 HTTP/1.1\r\nHost: {address}\r\n"
        f"X-Huron-Subject: root\r\nContent-Length: {len(content)}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    )
    connection.sendall(headers.encode() + content[:65536])
    target = volume / ".staging" / uuid.UUID(ledger["id"]).hex / "payload/file"
    for _ in range(100):
        if target.exists() and target.stat().st_size == 65536:
            break
        time.sleep(0.1)
    assert target.exists() and target.stat().st_size == 65536
    print("LEGACY_HTTP_UPLOAD_ADMITTED", flush=True)
    postgres = json.loads(subprocess.check_output([*engine, "inspect", "postgres"]))[0]
    ip = postgres["NetworkSettings"]["Networks"]["huron-proof"]["IPAddress"]

    async def fence_database():
        """Disable application roles through the real dedicated maintenance identity."""
        async with asyncpg.create_pool(
            host=ip, user="cutover", password="maintenance-password", database="huron"
        ) as pool:
            await PostgresRoleExclusion(pool).exclude(("old_app",), "new_app")

    asyncio.run(fence_database())
    connection.sendall(content[65536:131072])
    for _ in range(100):
        if target.stat().st_size == 131072:
            break
        time.sleep(0.1)
    assert target.stat().st_size == 131072
    print("LEGACY_HTTP_WRITE_SURVIVED_SQL_FENCE", flush=True)
    evidence = controller.establish(0, uuid.uuid4())
    assert writer in evidence.terminated_writers
    controller.check(0, evidence)
    after = target.read_bytes()
    time.sleep(0.4)
    assert target.read_bytes() == after
    with contextlib.suppress(ConnectionResetError):
        assert connection.recv(4096) == b""
    connection.close()
    client.close()
    try:
        controller.restart(0)
    except ValueError:
        pass
    else:
        raise AssertionError("restart admitted while fenced")
    print("LEGACY_WRITER_TERMINATED_RESTART_EXCLUDED", writer, flush=True)
    _rejected_legacy_restart(root, engine)
    _socket_cutover(root, engine, ip)


def _rejected_legacy_restart(root: pathlib.Path, engine: list[str]) -> None:
    """The historical artifact fails startup when retried with its revoked credentials."""
    from huron.applications.lakectl.engine import LocalEngine
    from huron.applications.lakectl.settings import ControllerSettings

    settings = ControllerSettings.load(root / "settings.json")
    specification = settings.application_specification()
    assert "replacement-password" not in str(specification)
    identifier = LocalEngine(settings.engine_socket).start(specification)
    try:
        for _ in range(100):
            state = json.loads(subprocess.check_output([*engine, "inspect", identifier]))[0][
                "State"
            ]
            if not state["Running"]:
                break
            time.sleep(0.1)
        assert not state["Running"]
        logs = subprocess.check_output([*engine, "logs", identifier], stderr=subprocess.STDOUT)
        assert b"old_app" in logs and b"not permitted to log in" in logs
        assert state["ExitCode"] != 0
        print("LEGACY_REVOKED_IDENTITY_STARTUP_REFUSED", flush=True)
    finally:
        subprocess.run([*engine, "rm", "--force", identifier], check=True)


def _socket_cutover(root: pathlib.Path, engine: list[str], database_address: str) -> None:
    """Authenticate real peers and run the wired cutover against actual hierarchy and storage."""
    import asyncio

    from pydantic import SecretStr

    from huron.applications.lakectl.exclusion import ControllerClient
    from huron.applications.lakectl.settings import ControllerSettings, MaintenanceSettings
    from huron.applications.lakectl.wiring import prepare

    socket_directory = pathlib.Path(tempfile.mkdtemp(prefix="huron-controller-test-", dir="/run"))
    socket_directory.chmod(0o755)
    settings = ControllerSettings.load(root / "settings.json").model_copy(
        update={"socket_path": socket_directory / "controller.sock"}
    )
    (root / "settings.json").write_text(settings.model_dump_json())
    invocation = [
        str(root / "venv/bin/python"),
        "-m",
        "huron.applications.lakectl.main",
        "controller",
        "--config",
        str(root / "settings.json"),
    ]
    process = None
    try:
        with (root / "controller.log").open("w") as output:
            process = subprocess.Popen(invocation, stdout=output, stderr=subprocess.STDOUT)
            _await_controller(settings.socket_path, process)
            client = ControllerClient(settings.socket_path)
            grant = asyncio.run(client.authenticate())
            assert grant.operator == "local:0" and grant.root_id == settings.root_id
            peer_program = (
                "import socket,json; s=socket.socket(socket.AF_UNIX); "
                f"s.connect({str(settings.socket_path)!r}); "
                's.sendall(b\'{"operation":"authenticate"}\\n\'); '
                "assert json.loads(s.recv(65536))['ok'] is False"
            )
            subprocess.run(
                [
                    "setpriv",
                    "--reuid",
                    "1002",
                    "--regid",
                    "1002",
                    "--clear-groups",
                    "python3",
                    "-c",
                    peer_program,
                ],
                check=True,
            )
            maintenance = MaintenanceSettings(
                controller_socket=settings.socket_path,
                database_url=SecretStr(
                    f"postgresql://cutover:maintenance-password@{database_address}/huron"
                ),
            )
            record = asyncio.run(prepare(maintenance, uuid.uuid4()))
            asyncio.run(client.check(record.fence))
            asyncio.run(client.validate_certificate(record))
            subprocess.run([*engine, "exec", "postgres", "psql", "-U", "owner", "-d", "huron",
                            "-c", "ALTER ROLE new_app LOGIN"], check=True)
            try:
                asyncio.run(client.validate_certificate(record))
            except PermissionError:
                pass
            else:
                raise AssertionError("consumer accepted a live SQL exclusion loss")
            subprocess.run([*engine, "exec", "postgres", "psql", "-U", "owner", "-d", "huron",
                            "-c", "ALTER ROLE new_app NOLOGIN"], check=True)
            try:
                asyncio.run(client.validate_certificate(record))
            except PermissionError:
                pass
            else:
                raise AssertionError("restored SQL observations revived endorsement")
            record = asyncio.run(prepare(maintenance, uuid.uuid4()))
            asyncio.run(client.validate_certificate(record))
            print("LIVE_SQL_CONSUMER_REVOCATION_AND_FRESH_VERIFICATION_PROVED", flush=True)
            print("AUTHENTICATED_WIRED_CUTOVER_RECORDED", record.report_digest, flush=True)
            _foreign_writer_refused(engine, client, record.fence)
            _descendant_writers_refused(engine, client, record.fence)
            process.terminate()
            process.wait(timeout=20)
            settings.socket_path.unlink(missing_ok=True)
            process = subprocess.Popen(invocation, stdout=output, stderr=subprocess.STDOUT)
            _await_controller(settings.socket_path, process)
            try:
                asyncio.run(client.check(record.fence))
            except PermissionError:
                pass
            else:
                raise AssertionError("a restarted controller accepted an earlier generation")
            process.terminate()
            process.wait(timeout=20)
            try:
                asyncio.run(client.check(record.fence))
            except OSError:
                pass
            else:
                raise AssertionError("an unreachable controller supplied exclusion proof")
            print("CONTROLLER_FOREIGN_GENERATION_UNREACHABLE_REFUSED", flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        settings.socket_path.unlink(missing_ok=True)
        socket_directory.rmdir()


def _await_controller(path: pathlib.Path, process: subprocess.Popen) -> None:
    """Wait for the actual controller endpoint while refusing failed process startup."""
    for _ in range(100):
        assert process.poll() is None, "controller process failed during startup"
        if path.exists():
            return
        time.sleep(0.1)
    raise AssertionError("controller socket never became available")


def _foreign_writer_refused(engine: list[str], client, evidence) -> None:
    """A real foreign container holding the protected volume invalidates complete exclusion."""
    import asyncio

    identifier = subprocess.check_output(
        [
            *engine,
            "create",
            "--network",
            "huron-proof",
            "--volume",
            "huron-proof:/data",
            "docker.io/library/python:3.12-slim-bookworm",
            "sleep",
            "60",
        ],
        text=True,
    ).strip()
    try:
        try:
            asyncio.run(client.check(evidence))
        except PermissionError:
            pass
        else:
            raise AssertionError("foreign volume holder did not invalidate exclusion")
    finally:
        subprocess.run([*engine, "rm", "--force", identifier], check=True)


def _descendant_writers_refused(engine: list[str], client, evidence) -> None:
    """Real running directory and file bind holders prevent both checking and establishment."""
    import asyncio
    import uuid

    root = asyncio.run(client.describe()).path
    organization = root / "organization"
    payload = next(organization.rglob("CURRENT.json"))
    for source in (organization, payload):
        identifier = subprocess.check_output(
            [*engine, "run", "--detach", "--network", "huron-proof",
             "--volume", f"{source}:/foreign", "docker.io/library/python:3.12-slim-bookworm",
             "sleep", "300"], text=True,
        ).strip()
        try:
            for operation in (
                client.check(evidence),
                client.establish(asyncio.run(client.authenticate()), uuid.uuid4()),
            ):
                try:
                    asyncio.run(operation)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("foreign descendant writer escaped complete inventory")
            inspected = json.loads(subprocess.check_output([*engine, "inspect", identifier]))[0]
            assert inspected["State"]["Running"]
            print("FOREIGN_DESCENDANT_WRITER_REFUSED", str(source.relative_to(root)), flush=True)
        finally:
            subprocess.run([*engine, "rm", "--force", identifier], check=True)


def main() -> None:
    """Dispatch isolated fixture setup or its dependency-equipped runtime scenario."""
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("provision", "scenario"))
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    args = parser.parse_args()
    if args.operation == "provision":
        provision(*args.paths)
    else:
        scenario(args.paths[0])


if __name__ == "__main__":
    main()
