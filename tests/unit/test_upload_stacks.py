"""The development stacks run one tusd with the agreed flags, behind the upload proxy, as the
host user over the lake, and prepare the lake before the API starts."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from huron.core.storage import MARKER_FILE, OBJECT_DIR, UPLOAD_DIR

ROOT = Path(__file__).resolve().parents[2]
UPLOADS: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.uploads.yml").read_text())
APP: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.app.yml").read_text())
DEV_CONFIG: dict[str, Any] = yaml.safe_load((ROOT / "huron.dev.yaml").read_text())
TUSD_IMAGE, NGINX_IMAGE = "tusproject/tusd:v2.10.1", "nginx:1.31.8"
LAKE = "${HURON_LAKE_SOURCE:-/data1/huron}:${HURON_LAKE_PATH:-/data1/huron}"
HOST_USER = "${HURON_UID:-1000}:${HURON_GID:-1000}"
#: "Recommended tusd flags" of plan 2, for the API at 127.0.0.1:8080 and max_upload_bytes 0.
TUSD_FLAGS = [
    "-host=127.0.0.1",
    "-port=1081",
    "-base-path=/files/",
    "-upload-dir=${HURON_LAKE_PATH:-/data1/huron}/.tus-uploads",
    "-behind-proxy",
    "-disable-download",
    "-disable-termination",
    "-disable-concatenation",
    "-max-size=0",
    "-file-perms=0600",
    "-dir-perms=0700",
    "-hooks-http=http://127.0.0.1:8080/api/v1/uploads/hooks",
    "-hooks-http-forward-headers=Authorization",
    "-hooks-enabled-events=pre-create,pre-finish",
    "-hooks-http-timeout=60s",
    "-hooks-http-retry=3",
    "-hooks-http-backoff=1s",
    "-request-completion-timeout=60s",
    "-network-timeout=2m",
]


def test_tusd_runs_with_the_recommended_flags_as_the_host_user_over_the_lake() -> None:
    tusd = UPLOADS["services"]["uploads"]
    assert (tusd["image"], tusd["pull_policy"]) == (TUSD_IMAGE, "never")
    assert tusd["command"] == TUSD_FLAGS
    assert (tusd["user"], tusd["volumes"], tusd["network_mode"]) == (HOST_USER, [LAKE], "host")


def test_tusd_removes_the_lock_files_before_it_starts() -> None:
    tusd = UPLOADS["services"]["uploads"]
    shell, flag, script, name = tusd["entrypoint"]
    assert (shell, flag, name) == ("sh", "-c", "tusd")
    assert script.splitlines() == [
        'cd "$$HURON_UPLOAD_DIR" && rm -f -- *.lock *.lock.* *.stop',
        'exec tusd "$$@"',
    ]
    assert tusd["environment"] == {
        "HURON_UPLOAD_DIR": "${HURON_LAKE_PATH:-/data1/huron}/.tus-uploads"
    }


def test_each_stack_starts_one_tusd_and_no_more() -> None:
    for services in (UPLOADS["services"], APP["services"]):
        resolved = {name: _resolved(services, name) for name in services}
        assert [name for name, s in resolved.items() if s.get("image") == TUSD_IMAGE] == ["uploads"]
        assert not {"deploy", "scale", "restart"} & set(resolved["uploads"])


def test_the_proxy_renders_the_template_with_its_three_variables_only() -> None:
    proxy = UPLOADS["services"]["uploads-proxy"]
    assert (proxy["image"], proxy["pull_policy"], proxy["user"]) == (
        NGINX_IMAGE,
        "never",
        HOST_USER,
    )
    assert proxy["command"] == ["nginx", "-c", "/tmp/nginx-uploads.conf", "-g", "daemon off;"]
    environment = proxy["environment"]
    assert environment["NGINX_ENVSUBST_TEMPLATE_DIR"] == "/etc/huron"
    assert environment["NGINX_ENVSUBST_TEMPLATE_SUFFIX"] == ".template"
    assert environment["NGINX_ENVSUBST_OUTPUT_DIR"] == "/tmp"
    assert (
        environment["NGINX_ENVSUBST_FILTER"] == "^HURON_(API_UPSTREAM|UPLOADS_HOST|UPLOADS_PROTO)$$"
    )
    assert environment["HURON_API_UPSTREAM"] == "127.0.0.1:8080"
    assert proxy["volumes"] == [
        "./deploy/openshift/nginx-uploads.conf.template:/etc/huron/nginx-uploads.conf.template:ro"
    ]


def test_the_uploads_url_of_the_dev_configuration_is_the_public_address_of_the_proxy() -> None:
    proxy = UPLOADS["services"]["uploads-proxy"]["environment"]
    public = f"{proxy['HURON_UPLOADS_PROTO']}://{proxy['HURON_UPLOADS_HOST']}/files/"
    assert DEV_CONFIG["uploads_url"] == public == "http://127.0.0.1:1080/files/"
    assert f"-hooks-http-timeout={DEV_CONFIG['upload_hook_timeout']}s" in TUSD_FLAGS
    assert DEV_CONFIG["lake_path"] == "/data1/huron"


def test_the_docker_application_takes_uploads_on_127_0_0_1_port_1080() -> None:
    services = APP["services"]
    assert "127.0.0.1:1080:1080" in services["net"]["ports"]
    for name in ("uploads", "uploads-proxy"):
        assert services[name]["network_mode"] == "service:net"
        assert services[name]["extends"] == {"file": "docker-compose.uploads.yml", "service": name}
    lake_init = services["uploads"]["depends_on"]["lake-init"]
    assert lake_init == {"condition": "service_completed_successfully"}


def test_the_docker_api_runs_as_the_host_user_after_the_lake_is_prepared() -> None:
    services = APP["services"]
    api, init = services["api"], services["lake-init"]
    assert (api["user"], init["user"]) == (HOST_USER, HOST_USER)
    assert LAKE in api["volumes"] and LAKE in init["volumes"]
    assert api["depends_on"]["lake-init"] == {"condition": "service_completed_successfully"}
    assert api["environment"]["HURON_SERVICE_UID"] == "${HURON_UID:-1000}"
    assert api["environment"]["HURON_SERVICE_GROUP"] == "${HURON_GROUP:-huron}"
    assert init["command"] == [
        "python",
        "/opt/huron/dev-provision.py",
        "--config",
        "/etc/huron/huron.yaml",
    ]


def test_the_docker_seed_uploads_through_the_proxy_and_does_not_mount_the_lake() -> None:
    seed = APP["services"]["seed"]
    assert seed["depends_on"]["uploads-proxy"] == {"condition": "service_healthy"}
    assert "HURON_SEED_LAKE_DIR" not in seed["environment"]
    assert LAKE not in seed["volumes"]
    assert seed["user"] == "node"


def test_dev_provision_prepares_the_lake_path_and_each_declared_organization(
    tmp_path: Path,
) -> None:
    lake = tmp_path / "lake"
    (lake / "geo-root").mkdir(parents=True)
    config = tmp_path / "huron.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "instance_id": "0192b6a0-0000-7000-8000-000000000001",
                "lake_path": str(lake),
                "organizations": [
                    {"name": "helio"},
                    {"name": "geo", "root": str(lake / "geo-root")},
                ],
            }
        )
    )
    first = _provision(config)
    assert first.returncode == 0, first.stderr
    for directory in (lake, lake / "helio", lake / "geo-root" / "geo"):
        assert (directory / MARKER_FILE).is_file()
    assert (lake / UPLOAD_DIR).stat().st_mode & 0o7777 == 0o700
    assert (lake / "helio" / OBJECT_DIR).stat().st_mode & 0o7777 == 0o700
    assert (lake / "helio").stat().st_uid == os.getuid()
    again = _provision(config)
    assert again.returncode == 0, again.stderr


def test_dev_provision_refuses_a_configuration_without_a_lake_path(tmp_path: Path) -> None:
    config = tmp_path / "huron.yaml"
    config.write_text("instance_id: 0192b6a0-0000-7000-8000-000000000001\n")
    refused = _provision(config)
    assert refused.returncode == 2
    assert refused.stderr == f"dev-provision: {config} sets no lake_path\n"


def _provision(config: Path) -> subprocess.CompletedProcess[str]:
    """Run scripts/dev-provision.py with the CLI of this environment on its PATH."""
    environment = {
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(config.parent),
        "XDG_CONFIG_HOME": str(config.parent / "config"),
        "XDG_STATE_HOME": str(config.parent / "state"),
    }
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev-provision.py"), "--config", str(config)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _resolved(services: dict[str, Any], name: str) -> dict[str, Any]:
    """The service ``name`` with the service that it extends below its own keys."""
    service = services[name]
    extends = service.get("extends")
    if extends is None:
        return dict(service)
    base: dict[str, Any] = UPLOADS["services"][extends["service"]]
    return {**base, **service}
