"""Real tusd and nginx in Docker containers in front of an API on the host.

The two containers are the services ``uploads`` and ``uploads-proxy`` of
``docker-compose.uploads.yml``: the same images, entrypoint, flags, environment and nginx
template. Only the ports, the addresses of the API and of the proxy, and the lake path change,
so that a test runs next to a development stack. The containers use host networking and run as
the user of the test, with the lake bound at its own path. The images must be in the local cache:
a run never pulls.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.support.api import free_port

__all__ = ["COMPOSE_FILE", "HOOK_TIMEOUT", "NGINX_TEMPLATE", "UploadStack", "compose_service"]

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.uploads.yml"
NGINX_TEMPLATE = ROOT / "deploy/openshift/nginx-uploads.conf.template"
#: How long the containers have to answer, in seconds.
DEADLINE = 30.0
#: The ports and the API address of the compose file, which the stack replaces.
_PROXY_PORT, _TUSD_PORT, _API = "1080", "1081", "127.0.0.1:8080"
_VARIABLE = re.compile(r"\$\{(?P<name>\w+)(?::-(?P<default>[^}]*))?\}")


def compose_service(name: str, environment: dict[str, str]) -> dict[str, Any]:
    """The service ``name`` of the compose file, with its variables replaced as Compose does:
    ``${NAME}`` and ``${NAME:-default}`` from ``environment``, and ``$$`` as ``$``.
    """
    document = yaml.safe_load(COMPOSE_FILE.read_text())
    service: dict[str, Any] = _interpolated(document["services"][name], environment)
    return service


def hook_timeout() -> int:
    """tusd's hook timeout in seconds: the ``-hooks-http-timeout`` flag of the compose file."""
    command = yaml.safe_load(COMPOSE_FILE.read_text())["services"]["uploads"]["command"]
    (flag,) = [flag for flag in command if flag.startswith("-hooks-http-timeout=")]
    return int(flag.removeprefix("-hooks-http-timeout=").removesuffix("s"))


#: tusd's hook timeout in seconds, which the API of a test reports to the CLI.
HOOK_TIMEOUT = hook_timeout()


class UploadStack:
    """tusd and the upload proxy for the API at ``127.0.0.1:<api port>``, over the lake ``lake``.

    ``work`` holds the rendered nginx template. :attr:`url` is the uploads URL of the proxy.
    """

    def __init__(self, lake: Path, work: Path) -> None:
        self.lake = lake
        self.proxy_port = free_port()
        self.tusd_port = free_port()
        self._work = work
        self._name = f"huron-it-{uuid.uuid4().hex[:12]}"
        self._started: list[str] = []
        self._api_port = 0
        self._user = f"{os.getuid()}:{os.getgid()}"
        self._environment = {"HURON_LAKE_SOURCE": str(lake), "HURON_LAKE_PATH": str(lake)}

    @property
    def url(self) -> str:
        """The uploads URL of the proxy, as ``uploads_url`` names it."""
        return f"http://127.0.0.1:{self.proxy_port}/files/"

    @property
    def tusd(self) -> str:
        """The name of the tusd container."""
        return f"{self._name}-tusd"

    @property
    def proxy(self) -> str:
        """The name of the nginx container."""
        return f"{self._name}-proxy"

    def start(self, api_port: int) -> None:
        """Start tusd, then the proxy; return when the proxy answers ``/readyz`` from tusd.

        When a step fails, the stack removes each container that it started, then raises.
        """
        self._api_port = api_port
        try:
            self.start_tusd()
            self._start_proxy()
            self.wait_ready()
        except BaseException:
            self.close()
            raise

    def start_tusd(self) -> None:
        """Start the tusd container, which first removes the lock files of ``.tus-uploads``."""
        service = compose_service("uploads", self._environment)
        entrypoint = list(service["entrypoint"])
        command = [self._tusd_flag(flag) for flag in service["command"]]
        environment = [f"--env={key}={value}" for key, value in service["environment"].items()]
        self._run(
            self.tusd,
            [*environment, f"--entrypoint={entrypoint[0]}", f"--volume={self.lake}:{self.lake}"],
            [service["image"], *entrypoint[1:], *command],
        )

    def kill_tusd(self) -> None:
        """Kill the tusd container with ``SIGKILL`` and remove it."""
        self._docker("kill", self.tusd)
        self._docker("rm", "--force", self.tusd)
        self._started.remove(self.tusd)

    def wait_ready(self) -> None:
        """Wait until the proxy answers ``/readyz`` from tusd."""
        deadline = time.monotonic() + DEADLINE
        while True:
            try:
                answer = httpx.get(f"http://127.0.0.1:{self.proxy_port}/readyz", timeout=2)
                if answer.is_success:
                    return
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise AssertionError(f"the upload proxy is not ready:\n{self.logs()}")
            time.sleep(0.1)

    def nginx_test(self) -> subprocess.CompletedProcess[str]:
        """``nginx -t`` on the configuration that the proxy rendered."""
        return subprocess.run(
            ["docker", "exec", self.proxy, "nginx", "-t", "-c", "/tmp/nginx-uploads.conf"],
            capture_output=True,
            text=True,
            check=False,
        )

    def logs(self) -> str:
        """The output of each container that the stack started."""
        return "\n".join(
            f"--- {name}\n{self._docker('logs', name, check=False)}" for name in self._started
        )

    def close(self) -> None:
        """Remove every container that the stack started or tried to start."""
        for name in reversed(self._started):
            self._docker("rm", "--force", name, check=False)
        self._started.clear()

    def _start_proxy(self) -> None:
        service = compose_service("uploads-proxy", self._environment)
        template = NGINX_TEMPLATE.read_text()
        template = template.replace(f"listen {_PROXY_PORT};", f"listen {self.proxy_port};")
        template = template.replace(f"127.0.0.1:{_TUSD_PORT};", f"127.0.0.1:{self.tusd_port};")
        rendered = self._work / "nginx-uploads.conf.template"
        rendered.write_text(template)
        rendered.chmod(0o644)
        environment = {
            **service["environment"],
            "HURON_API_UPSTREAM": f"127.0.0.1:{self._api_port}",
            "HURON_UPLOADS_HOST": f"127.0.0.1:{self.proxy_port}",
        }
        options = [f"--env={key}={value}" for key, value in environment.items()]
        options.append(f"--volume={rendered}:/etc/huron/nginx-uploads.conf.template:ro")
        self._run(self.proxy, options, [service["image"], *service["command"]])

    def _tusd_flag(self, flag: str) -> str:
        if flag == f"-port={_TUSD_PORT}":
            return f"-port={self.tusd_port}"
        return flag.replace(f"http://{_API}/", f"http://127.0.0.1:{self._api_port}/")

    def _run(self, name: str, options: list[str], arguments: list[str]) -> None:
        # A failed `docker run` can leave a created container, so close() removes it too.
        self._started.append(name)
        self._docker(
            "run",
            "--detach",
            "--pull=never",
            f"--name={name}",
            "--network=host",
            f"--user={self._user}",
            *options,
            *arguments,
        )

    def _docker(self, *arguments: str, check: bool = True) -> str:
        done = subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, check=False, timeout=60
        )
        if check and done.returncode != 0:
            raise AssertionError(f"docker {' '.join(arguments)}: {done.stderr}")
        return done.stdout + done.stderr


def _interpolated(value: Any, environment: dict[str, str]) -> Any:
    if isinstance(value, str):
        replaced = _VARIABLE.sub(
            lambda match: environment.get(match["name"], match["default"] or ""),
            value.replace("$$", "\0"),
        )
        return replaced.replace("\0", "$")
    if isinstance(value, list):
        return [_interpolated(item, environment) for item in value]
    if isinstance(value, dict):
        return {key: _interpolated(item, environment) for key, item in value.items()}
    return value
