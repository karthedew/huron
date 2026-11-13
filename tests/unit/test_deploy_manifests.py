"""The kustomize base and the local overlay run one writer of the lake and one tusd behind the
upload proxy, with probes, grace periods, users and paths that agree with the service
configuration that the API reads.

Each rule is a function that lists the problems that it finds. A rule passes on the files of the
repository (the rendering of ``kubectl kustomize``, or a ``kustomization.yaml``), and a copy of
those files with one change breaks it.
"""

import copy
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml
from pydantic import ValidationError

from huron.applications.api.disk import PROBE_TIMEOUT
from huron.applications.api.settings import Settings, StrictYamlSource
from huron.core.storage import MARKER_FILE, OBJECT_DIR, UPLOAD_DIR
from tests.support.devprovision import run_dev_provision

type Manifest = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
BASE, LOCAL = "deploy/openshift", "deploy/local"
TUSD_IMAGE, NGINX_IMAGE = "tusproject/tusd:v2.10.1", "nginx:1.31.8"
#: The images of the local overlay: the API image of this repository and the cached images.
LOCAL_IMAGES = {
    "huron:local",
    TUSD_IMAGE,
    NGINX_IMAGE,
    "postgres:16",
    "quay.io/keycloak/keycloak:26.0",
}
LOCK_CLEANUP = 'cd "$HURON_UPLOAD_DIR" && rm -f -- *.lock *.lock.* *.stop'
PROXY_ARGS = ["nginx", "-c", "/tmp/nginx-uploads.conf", "-g", "daemon off;"]
UPLOAD_INGRESS_ANNOTATIONS = {
    "nginx.ingress.kubernetes.io/proxy-body-size": "0",
    "nginx.ingress.kubernetes.io/proxy-request-buffering": "off",
    "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
    "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
}
INSTANCE_PLACEHOLDER = "replace-with-the-uuid-written-into-the-share-markers"
#: The prefixes of the variables that the script or its fakes read, which a test sets itself.
SCRIPT_VARIABLES = ("K8S_LOCAL_", "KUBECONFIG", "FAKE_", "CALLS")
#: The variables that change how bash starts (BASH_FUNC_ is a prefix), and HOME, which a test
#: fixes.
SHELL_VARIABLES = {"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "HOME"}
SHELL_PREFIXES = ("BASH_FUNC_",)
#: HOME of the script in a test: a path that does not exist and that no lake of a test lies above.
TEST_HOME = "/nonexistent/huron-k8s-local-test-home"
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"}


@pytest.fixture(params=[BASE, LOCAL])
def rendered(request: pytest.FixtureRequest) -> list[Manifest]:
    """A copy of the rendering of the base or of the local overlay, free to change."""
    return copy.deepcopy(_render(request.param))


@pytest.fixture
def local() -> list[Manifest]:
    """A copy of the rendering of the local overlay, free to change."""
    return copy.deepcopy(_render(LOCAL))


@pytest.fixture
def base() -> list[Manifest]:
    """A copy of the rendering of the base, free to change."""
    return copy.deepcopy(_render(BASE))


@pytest.fixture
def load_settings(tmp_path: Path) -> Callable[[list[Manifest]], Settings]:
    """Read the ``huron.yaml`` of a rendering with the API's strict reader and validators."""

    def load(manifests: list[Manifest]) -> Settings:
        path = tmp_path / "huron.yaml"
        path.write_text(_service_configuration(manifests), encoding="utf-8")
        values = StrictYamlSource(Settings, path)()
        # The base leaves instance_id to the operator, so the API refuses it unchanged.
        if values["instance_id"] == INSTANCE_PLACEHOLDER:
            values["instance_id"] = "0192b6a0-0000-7000-8000-000000000001"
        return Settings.model_validate(values)

    return load


#: kubectl, docker, id and find for scripts/k8s-local.sh. kubectl, docker and find record their
#: arguments in $CALLS, and find deletes nothing. The fakes answer from the variables
#: FAKE_CONTEXT, FAKE_NODE, FAKE_MOUNTS, FAKE_UID and FAKE_GID. docker fails for a node
#: container when FAKE_NO_CONTAINER is set. A stat in the node runs the real stat, with the
#: format of the script, on FAKE_NODE_LAKE: the host directory that the node shows at /huron-lake.
FAKE_KUBECTL = """#!/bin/sh
echo "kubectl $*" >>"$CALLS"
case "$*" in
  *"config current-context"*) echo "$FAKE_CONTEXT" ;;
  *"get nodes"*) printf '%s' "$FAKE_NODE" ;;
esac
"""
FAKE_DOCKER = """#!/bin/sh
echo "docker $*" >>"$CALLS"
case "$1 $2" in
  "inspect --type") [ -z "$FAKE_NO_CONTAINER" ] || exit 1 ;;
  "inspect --format") printf '%s\\n' "$FAKE_MOUNTS" ;;
  "exec "*) if [ "$3" = stat ]; then exec stat -c "$5" "$FAKE_NODE_LAKE"; fi ;;
esac
"""
FAKE_FIND = """#!/bin/sh
echo "find $*" >>"$CALLS"
"""
FAKE_ID = """#!/bin/sh
case "$1" in
  -u) echo "$FAKE_UID" ;;
  -g) echo "$FAKE_GID" ;;
esac
"""


class FakeCluster:
    """scripts/k8s-local.sh with a fake kubectl, docker, id and find, which delete nothing.

    By default the fakes answer as the local cluster: the context of the kubeconfig is
    ``kind-huron-local``, its one node binds the lake directory at /huron-lake, and the user is
    the service user of the overlay on each host.
    """

    def __init__(self, directory: Path) -> None:
        tools = directory / "bin"
        tools.mkdir()
        self.tools = tools
        fakes = {"kubectl": FAKE_KUBECTL, "docker": FAKE_DOCKER, "id": FAKE_ID, "find": FAKE_FIND}
        for name, text in fakes.items():
            (tools / name).write_text(text, encoding="utf-8")
            (tools / name).chmod(0o755)
        kubeconfig = directory / "kubeconfig"
        kubeconfig.write_text("", encoding="utf-8")
        self.lake = directory / "lake"
        lake = self.lake
        settings = _script_settings()
        self._calls = directory / "calls"
        self.target = f"--kubeconfig {kubeconfig} --context kind-huron-local"
        self.environment = {
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(self._calls),
            "K8S_LOCAL_KUBECONFIG": str(kubeconfig),
            "K8S_LOCAL_CONTEXT": "kind-huron-local",
            "K8S_LOCAL_LAKE": str(lake),
            "FAKE_CONTEXT": "kind-huron-local",
            "FAKE_NODE": "huron-local-control-plane",
            "FAKE_MOUNTS": f"/lib/modules=/lib/modules\n{lake}=/huron-lake",
            "FAKE_NODE_LAKE": str(lake),
            "FAKE_NO_CONTAINER": "",
            "FAKE_UID": settings["service_uid"],
            "FAKE_GID": settings["service_gid"],
        }

    def run(self, verb: str, **changes: str) -> subprocess.CompletedProcess[str]:
        """Run the script with ``verb`` and the fake tools, with ``changes`` to the variables."""
        return _script(verb, check=False, **{**self.environment, **changes})

    def calls(self) -> list[str]:
        """Each call of the fake kubectl, docker and find, in order."""
        if not self._calls.exists():
            return []
        return self._calls.read_text(encoding="utf-8").splitlines()


@pytest.fixture
def fake_cluster(tmp_path: Path) -> FakeCluster:
    """The script with fake tools that answer as the local cluster."""
    return FakeCluster(tmp_path)


def test_kubectl_renders_the_base_and_the_local_overlay() -> None:
    assert shutil.which("kubectl"), "the manifest tests render with kubectl kustomize"
    assert {_name(m) for m in _render(BASE)} >= {
        ("Deployment", "huron"),
        ("Deployment", "huron-uploads"),
        ("Service", "huron-uploads"),
        ("Route", "huron-uploads"),
        ("PersistentVolumeClaim", "huron-lake"),
    }
    assert {_name(m) for m in _render(LOCAL)} >= {
        ("Namespace", "huron"),
        ("PersistentVolume", "huron-local-lake"),
        ("StatefulSet", "huron-postgres"),
        ("Job", "huron-lake-init"),
        ("Ingress", "huron"),
        ("Ingress", "huron-uploads"),
    }


def test_the_api_runs_one_replica_that_stops_before_the_next_starts(
    rendered: list[Manifest],
) -> None:
    assert _writer_problems(rendered) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        pytest.param(
            lambda m: _replicas(m, "huron", 0), "the API runs 0 replicas, not 1", id="0-replicas"
        ),
        pytest.param(
            lambda m: _replicas(m, "huron", 2), "the API runs 2 replicas, not 1", id="2-replicas"
        ),
        pytest.param(
            lambda m: _rolling(m, "huron"),
            "the API does not use the strategy Recreate",
            id="rolling-update",
        ),
    ],
)
def test_a_changed_api_deployment_breaks_the_writer_rule(
    rendered: list[Manifest], change: Callable[[list[Manifest]], None], problem: str
) -> None:
    change(rendered)
    assert _writer_problems(rendered) == [problem]


def test_one_tusd_starts_after_its_lock_files_are_removed(rendered: list[Manifest]) -> None:
    assert _tusd_problems(rendered) == []
    pod = _pod(_one(rendered, "Deployment", "huron-uploads"))
    (cleanup,) = pod["initContainers"]
    assert cleanup["image"] == TUSD_IMAGE
    assert cleanup["command"] == ["sh", "-c", LOCK_CLEANUP]
    assert _env(cleanup)["HURON_UPLOAD_DIR"] == f"{_lake_path(rendered)}/{UPLOAD_DIR}"


CLEANER = "huron-uploads removes the lock files of tusd and"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        pytest.param(
            lambda m: _replicas(m, "huron-uploads", 0),
            f"{CLEANER} runs 0 replicas, not 1",
            id="0-replicas",
        ),
        pytest.param(
            lambda m: _replicas(m, "huron-uploads", 2),
            f"{CLEANER} runs 2 replicas, not 1",
            id="2-replicas",
        ),
        pytest.param(
            lambda m: _rolling(m, "huron-uploads"),
            f"{CLEANER} does not use the strategy Recreate",
            id="rolling-update",
        ),
        pytest.param(lambda m: _twin(m), "2 workloads run tusd, not 1", id="second-tusd"),
        pytest.param(
            lambda m: _no_cleanup(m),
            "huron-uploads starts tusd with no lock cleanup before it",
            id="no-cleanup",
        ),
    ],
)
def test_a_changed_upload_deployment_breaks_the_tusd_rule(
    rendered: list[Manifest], change: Callable[[list[Manifest]], None], problem: str
) -> None:
    change(rendered)
    assert _tusd_problems(rendered) == [problem]


def test_readiness_probes_the_lake_and_liveness_does_not(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    assert _probe_problems(rendered) == []
    api = _container(_one(rendered, "Deployment", "huron"), "api")
    # /readyz of the API runs the lake probe, hard links included, only with a lake path.
    assert load_settings(rendered).lake_path == Path(_lake_path(rendered))
    assert api["readinessProbe"]["httpGet"]["port"] == "http"
    assert {"name": "http", "containerPort": 8080} in api["ports"]
    assert api["readinessProbe"]["timeoutSeconds"] > PROBE_TIMEOUT


API, PROXY = ("huron", "api"), ("huron-uploads", "proxy")
ASKS_READYZ = {"httpGet": {"path": "/readyz", "port": "http"}}


@pytest.mark.parametrize(
    ("place", "probe", "change", "problem"),
    [
        (API, "readinessProbe", {"timeoutSeconds": 2}, "the readiness of api"),
        (API, "readinessProbe", {"periodSeconds": 10}, "the readiness of api"),
        (API, "readinessProbe", {"failureThreshold": 1}, "the readiness of api"),
        (API, "readinessProbe", {"httpGet": {"path": "/healthz"}}, "the readiness of api"),
        (API, "livenessProbe", ASKS_READYZ, "the liveness of api asks /readyz"),
        (PROXY, "readinessProbe", {"timeoutSeconds": 1}, "the readiness of proxy"),
        (PROXY, "livenessProbe", ASKS_READYZ, "the liveness of proxy asks /readyz"),
    ],
)
def test_a_changed_probe_breaks_the_probe_rule(
    rendered: list[Manifest],
    place: tuple[str, str],
    probe: str,
    change: dict[str, Any],
    problem: str,
) -> None:
    deployment, container = place
    _container(_one(rendered, "Deployment", deployment), container)[probe].update(change)
    (found,) = _probe_problems(rendered)
    assert found.startswith(problem)


def test_each_pod_waits_longer_than_the_longest_seal_before_it_is_killed(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    assert _grace_problems(rendered, load_settings(rendered)) == []


def test_a_grace_period_that_is_not_longer_than_the_hook_timeout_breaks_the_grace_rule(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    settings = load_settings(rendered)
    limit = int(settings.upload_hook_timeout.total_seconds())
    _pod(_one(rendered, "Deployment", "huron"))["terminationGracePeriodSeconds"] = limit
    assert _grace_problems(rendered, settings) == [
        f"huron waits {limit} s before it is killed, not more than the {limit} s of a seal"
    ]


def test_a_hook_timeout_of_tusd_other_than_the_setting_breaks_the_grace_rule(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    settings = load_settings(rendered)
    tusd = _container(_one(rendered, "Deployment", "huron-uploads"), "tusd")
    tusd["args"] = [_replaced(a, "-hooks-http-timeout=", "120s") for a in tusd["args"]]
    limit = int(settings.upload_hook_timeout.total_seconds())
    assert _grace_problems(rendered, settings) == [
        f"tusd waits 120 s for a hook, not the upload_hook_timeout of {limit} s"
    ]


def test_each_pod_on_the_lake_runs_as_the_service_user_at_the_lake_path(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    assert _lake_problems(rendered, load_settings(rendered)) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"runAsUser": 4242}, "huron-uploads runs as 4242, not the service user"),
        ({"supplementalGroups": []}, "huron-uploads does not have its group in supplementalGroups"),
        ({"runAsNonRoot": False}, "huron-uploads does not refuse to run as root"),
        (
            {"seccompProfile": {"type": "Unconfined"}},
            "huron-uploads has no seccomp profile RuntimeDefault",
        ),
    ],
)
def test_a_pod_on_the_lake_with_another_user_breaks_the_lake_rule(
    rendered: list[Manifest],
    load_settings: Callable[[list[Manifest]], Settings],
    change: dict[str, Any],
    problem: str,
) -> None:
    _pod(_one(rendered, "Deployment", "huron-uploads"))["securityContext"].update(change)
    assert _lake_problems(rendered, load_settings(rendered)) == [problem]


def test_a_lake_mount_at_another_path_breaks_the_lake_rule(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    api = _container(_one(rendered, "Deployment", "huron"), "api")
    (mount,) = [m for m in api["volumeMounts"] if m["name"] == "lake"]
    mount["mountPath"] = "/mnt/lake"
    assert _lake_problems(rendered, load_settings(rendered)) == [
        "huron mounts the lake at /mnt/lake, not at lake_path"
    ]


def test_the_upload_proxy_keeps_the_entrypoint_and_forwards_the_uploads_url(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    assert _proxy_problems(rendered, load_settings(rendered)) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"command": ["nginx"]}, "the proxy sets command, which skips the template step"),
        ({"args": ["nginx"]}, "the proxy does not start nginx with /tmp/nginx-uploads.conf"),
        ({"image": "nginx:latest"}, "the proxy runs nginx:latest, not nginx:1.31.8"),
    ],
)
def test_a_changed_proxy_breaks_the_proxy_rule(
    rendered: list[Manifest],
    load_settings: Callable[[list[Manifest]], Settings],
    change: dict[str, Any],
    problem: str,
) -> None:
    _container(_one(rendered, "Deployment", "huron-uploads"), "proxy").update(change)
    assert _proxy_problems(rendered, load_settings(rendered)) == [problem]


def test_an_uploads_url_that_the_proxy_does_not_forward_breaks_the_proxy_rule(
    rendered: list[Manifest], load_settings: Callable[[list[Manifest]], Settings]
) -> None:
    proxy = _container(_one(rendered, "Deployment", "huron-uploads"), "proxy")
    for variable in proxy["env"]:
        if variable["name"] == "HURON_UPLOADS_PROTO":
            variable["value"] = "http"
    (problem,) = _proxy_problems(rendered, load_settings(rendered))
    assert problem.startswith("the proxy forwards http://")


def test_the_api_refuses_the_base_until_the_operator_sets_the_instance(
    base: list[Manifest], tmp_path: Path
) -> None:
    path = tmp_path / "huron.yaml"
    path.write_text(_service_configuration(base), encoding="utf-8")
    values = StrictYamlSource(Settings, path)()
    assert values["instance_id"] == INSTANCE_PLACEHOLDER
    with pytest.raises(ValidationError, match="instance_id"):
        Settings.model_validate(values)


def test_the_service_configuration_has_no_mount_prefix(rendered: list[Manifest]) -> None:
    configuration = yaml.safe_load(_service_configuration(rendered))
    assert "mount_prefix" not in configuration
    assert {"lake_path", "uploads_url", "service_uid", "service_group"} <= set(configuration)
    assert "upload_hook_timeout" in configuration


def test_the_base_routes_wait_for_the_disk_work_and_the_final_patch(
    base: list[Manifest],
) -> None:
    api, uploads = _one(base, "Route", "huron"), _one(base, "Route", "huron-uploads")
    timeout = "haproxy.router.openshift.io/timeout"
    assert (api["metadata"]["annotations"][timeout], api["spec"]["host"]) == (
        "300s",
        "huron.apps.example.org",
    )
    assert uploads["metadata"]["annotations"][timeout] == "3600s"
    assert (uploads["spec"]["path"], uploads["spec"]["host"]) == ("/files", api["spec"]["host"])
    assert uploads["spec"]["to"]["name"] == "huron-uploads"
    service = _one(base, "Service", "huron-uploads")
    assert service["spec"]["ports"] == [{"name": "http", "port": 1080, "targetPort": "http"}]
    claim = _one(base, "PersistentVolumeClaim", "huron-lake")
    assert claim["spec"]["accessModes"] == ["ReadWriteMany"]
    assert {_name(m)[0] for m in base}.isdisjoint({"NetworkPolicy", "Ingress", "Namespace"})


def test_the_local_overlay_replaces_the_routes_with_ingresses(local: list[Manifest]) -> None:
    assert _local_problems(local) == []
    api = _one(local, "Ingress", "huron")
    annotations = api["metadata"]["annotations"]
    assert annotations["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "300"
    assert annotations["nginx.ingress.kubernetes.io/proxy-send-timeout"] == "300"
    for ingress in (api, _one(local, "Ingress", "huron-uploads")):
        assert ingress["spec"]["tls"] == [{"hosts": ["localhost"], "secretName": "huron-local-tls"}]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            lambda m: m.append({"kind": "Route", "metadata": {"name": "huron"}}),
            "the local overlay keeps a Route, which no router serves",
        ),
        (
            lambda m: _one(m, "Ingress", "huron-uploads")["metadata"]["annotations"].pop(
                "nginx.ingress.kubernetes.io/proxy-request-buffering"
            ),
            "the Ingress huron-uploads lacks the ingress-nginx settings of the uploads",
        ),
        (
            lambda m: m.remove(_one(m, "Job", "huron-lake-init")),
            "the local overlay has no Job huron-lake-init",
        ),
        (
            lambda m: _pod(_one(m, "Deployment", "huron"))["containers"].pop(),
            "the API pod holds api, keycloak, not api, keycloak and groups",
        ),
        (
            lambda m: _pod(_one(m, "Job", "huron-migrate"))["initContainers"][0][
                "securityContext"
            ].pop("readOnlyRootFilesystem"),
            "wait-for-postgres is not a restricted container",
        ),
        (
            lambda m: _pod(_one(m, "Job", "huron-migrate"))["initContainers"][0][
                "securityContext"
            ].pop("seccompProfile"),
            "wait-for-postgres is not a restricted container",
        ),
        (
            lambda m: _container(_one(m, "StatefulSet", "huron-postgres"), "postgres").update(
                imagePullPolicy="IfNotPresent"
            ),
            "postgres can pull its image",
        ),
        (
            lambda m: _container(_one(m, "StatefulSet", "huron-postgres"), "postgres").update(
                image="postgres:17"
            ),
            "postgres runs postgres:17, which the node does not get",
        ),
    ],
)
def test_a_changed_local_overlay_breaks_the_local_rule(
    local: list[Manifest], change: Callable[[list[Manifest]], object], problem: str
) -> None:
    change(local)
    assert _local_problems(local) == [problem]


def test_the_lake_of_the_local_overlay_is_a_directory_of_the_node(local: list[Manifest]) -> None:
    volume = _one(local, "PersistentVolume", "huron-local-lake")
    assert volume["spec"]["hostPath"] == {"path": "/huron-lake", "type": "Directory"}
    assert volume["spec"]["accessModes"] == ["ReadWriteMany"]
    assert volume["spec"]["claimRef"] == {"namespace": "huron", "name": "huron-lake"}
    claim = _one(local, "PersistentVolumeClaim", "huron-lake")
    assert claim["spec"]["volumeName"] == "huron-local-lake"
    assert claim["metadata"]["namespace"] == "huron"
    job = _one(local, "Job", "huron-lake-init")
    (init,) = _pod(job)["containers"]
    assert init["command"] == [
        "python",
        "/app/scripts/dev-provision.py",
        "--config",
        "/etc/huron/huron.yaml",
    ]
    configuration = _configmap_name(local, "huron-config")
    assert {"name": "config", "configMap": {"name": configuration}} in _pod(job)["volumes"]


def test_the_job_of_the_local_overlay_prepares_each_declared_organization(
    tmp_path: Path,
) -> None:
    configuration = yaml.safe_load(_service_configuration(_render(LOCAL)))
    lake = tmp_path / "lake"
    lake.mkdir()
    configuration["lake_path"] = str(lake)
    path = tmp_path / "huron.yaml"
    path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    finished = run_dev_provision(path)
    assert finished.returncode == 0, finished.stderr
    assert (lake / MARKER_FILE).is_file() and (lake / UPLOAD_DIR).is_dir()
    for organization in configuration["organizations"]:
        directory = lake / organization["name"]
        assert (directory / MARKER_FILE).is_file() and (directory / OBJECT_DIR).is_dir()


def test_the_script_of_the_local_cluster_makes_what_the_overlay_names(
    local: list[Manifest],
) -> None:
    settings = _script_settings()
    assert set(settings["images"].split()) == LOCAL_IMAGES
    volume = _one(local, "PersistentVolume", "huron-local-lake")
    assert (settings["volume"], settings["node_lake"]) == (
        volume["metadata"]["name"],
        volume["spec"]["hostPath"]["path"],
    )
    assert settings["namespace"] == _one(local, "Namespace", "huron")["metadata"]["name"]
    for name in ("huron", "huron-uploads"):
        (tls,) = _one(local, "Ingress", name)["spec"]["tls"]
        assert tls["secretName"] == settings["tls_secret"]
    api = _pod(_one(local, "Deployment", "huron"))
    volumes = {v["name"]: v.get("configMap", {}).get("name") for v in api["volumes"]}
    assert volumes["realm"] == settings["realm_configmap"]
    assert volumes["dev-groups"] == settings["groups_configmap"]
    groups = _container(_one(local, "Deployment", "huron"), "groups")
    assert f"/etc/huron-dev/{settings['groups_file']} 8082" in groups["command"][-1]
    uploads_url = yaml.safe_load(_service_configuration(local))["uploads_url"]
    assert f"{settings['api_url']}/files/" == uploads_url


def test_the_first_apply_holds_each_object_but_the_two_pods_that_need_the_jobs(
    local: list[Manifest],
) -> None:
    selector = _script_settings()["before_pods"]
    match = re.fullmatch(r"([\w./-]+) notin \(([\w,-]+)\)", selector)
    assert match is not None
    key, values = match[1], set(match[2].split(","))
    later = [m for m in local if m["metadata"].get("labels", {}).get(key) in values]
    assert sorted(_name(m) for m in later) == [
        ("Deployment", "huron"),
        ("Deployment", "huron-uploads"),
    ]


@pytest.mark.parametrize("name", ["lake", 'a&b c\'d \\ "e" #f: g'])
def test_the_kind_cluster_shows_the_lake_and_publishes_the_port_of_the_uploads(
    local: list[Manifest], tmp_path: Path, name: str
) -> None:
    lake = tmp_path / name
    cluster = yaml.safe_load(_script("kind-config", K8S_LOCAL_LAKE=str(lake)).stdout)
    (node,) = cluster["nodes"]
    volume = _one(local, "PersistentVolume", "huron-local-lake")
    assert node["extraMounts"] == [
        {"hostPath": str(lake), "containerPath": volume["spec"]["hostPath"]["path"]}
    ]
    port = urlsplit(yaml.safe_load(_service_configuration(local))["uploads_url"]).port
    assert node["extraPortMappings"] == [
        {"containerPort": 443, "hostPort": port, "listenAddress": "127.0.0.1"}
    ]
    settings = _script_settings()
    assert settings["context"] == f"kind-{cluster['name']}"
    assert urlsplit(settings["api_url"]).port == port


def test_the_kind_configuration_keeps_the_comments_of_its_template(tmp_path: Path) -> None:
    printed = _script("kind-config", K8S_LOCAL_LAKE=str(tmp_path / "a&b")).stdout
    template = (ROOT / LOCAL / "kind.yaml.template").read_text()
    comments = [line for line in template.splitlines() if line.startswith("#")]
    assert [line for line in printed.splitlines() if line.startswith("#")] == comments


ABOVE_HOME = "not be your home directory or a directory above it"


@pytest.mark.parametrize(
    ("lake", "refusal"),
    [
        pytest.param("relative/lake", "be an absolute path", id="relative"),
        pytest.param("/tmp/a\nb", "not hold a line break or a carriage return", id="line-break"),
        pytest.param("/tmp/a\rb", "not hold a line break or a carriage return", id="return"),
        pytest.param("/", ABOVE_HOME, id="root"),
        pytest.param("//", ABOVE_HOME, id="root-twice"),
        pytest.param("/.", ABOVE_HOME, id="root-dot"),
        pytest.param("{home}", ABOVE_HOME, id="home"),
        pytest.param("{home}/", ABOVE_HOME, id="home-slash"),
        pytest.param("{home}/.", ABOVE_HOME, id="home-dot"),
        pytest.param("{home}/..", ABOVE_HOME, id="home-parent"),
        pytest.param("{above}", ABOVE_HOME, id="above-home"),
        pytest.param("{link}", ABOVE_HOME, id="link-to-home"),
    ],
)
def test_the_kind_configuration_refuses_a_lake_that_kind_or_a_purge_cannot_take(
    tmp_path: Path, lake: str, refusal: str
) -> None:
    home = tmp_path / "users" / "me"
    home.mkdir(parents=True)
    (tmp_path / "link").symlink_to(home)
    path = lake.format(home=home, above=tmp_path / "users", link=tmp_path / "link")
    refused = _script("kind-config", check=False, HOME=str(home), K8S_LOCAL_LAKE=path)
    assert refused.returncode == 1 and refused.stdout == ""
    assert refused.stderr.startswith(f"k8s-local: K8S_LOCAL_LAKE must {refusal}")


def test_the_kind_configuration_refuses_the_home_directory_when_home_is_a_link(
    tmp_path: Path,
) -> None:
    home = tmp_path / "me"
    home.mkdir()
    (tmp_path / "link").symlink_to(home)
    refused = _script(
        "kind-config", check=False, HOME=str(tmp_path / "link"), K8S_LOCAL_LAKE=str(home)
    )
    assert refused.returncode == 1 and refused.stdout == ""
    assert refused.stderr.startswith(f"k8s-local: K8S_LOCAL_LAKE must {ABOVE_HOME}")


@pytest.mark.parametrize(
    "lake",
    [
        pytest.param("{home}x/lake", id="longer-name"),
        pytest.param("{parent}/m", id="shorter-name"),
        pytest.param("{home}/lake", id="below-home"),
        pytest.param("/{name}", id="same-name-at-the-root"),
    ],
)
def test_the_kind_configuration_takes_a_directory_beside_or_below_the_home_directory(
    tmp_path: Path, lake: str
) -> None:
    home = tmp_path / "me"
    path = lake.format(home=home, parent=tmp_path, name=home.name)
    printed = _script("kind-config", HOME=str(home), K8S_LOCAL_LAKE=path).stdout
    (node,) = yaml.safe_load(printed)["nodes"]
    assert node["extraMounts"][0]["hostPath"] == path


def test_the_script_runs_the_pods_as_the_user_and_group_of_the_overlay(
    local: list[Manifest],
) -> None:
    settings = _script_settings()
    for name in ("huron", "huron-uploads"):
        context = _pod(_one(local, "Deployment", name))["securityContext"]
        assert (str(context["runAsUser"]), str(context["runAsGroup"])) == (
            settings["service_uid"],
            settings["service_gid"],
        )


def test_down_deletes_the_namespace_and_the_volume_of_the_local_cluster(
    fake_cluster: FakeCluster,
) -> None:
    finished = fake_cluster.run("down")
    assert finished.returncode == 0, finished.stderr
    deletes = [c for c in fake_cluster.calls() if " delete " in c]
    assert deletes == [
        f"kubectl {fake_cluster.target} delete namespace huron --ignore-not-found --wait",
        f"kubectl {fake_cluster.target} delete persistentvolume huron-local-lake"
        " --ignore-not-found",
    ]


@pytest.mark.parametrize(
    ("make_lake", "changes", "messages"),
    [
        pytest.param(
            False,
            {"FAKE_MOUNTS": "/lib/modules=/lib/modules"},
            ["so it is not the local cluster"],
            id="node-without-the-lake",
        ),
        pytest.param(
            False,
            {"FAKE_CONTEXT": "kubernetes-admin@ocp-test"},
            ["Set K8S_LOCAL_KUBECONFIG to the kubeconfig of the local cluster"],
            id="another-context",
        ),
        pytest.param(
            False,
            {"FAKE_CONTEXT": "kind-huron-local-2"},
            ["is 'kind-huron-local-2', not 'kind-huron-local'"],
            id="context-with-a-longer-name",
        ),
        pytest.param(
            False,
            {"FAKE_CONTEXT": "x-kind-huron-local"},
            ["is 'x-kind-huron-local', not 'kind-huron-local'"],
            id="context-with-a-prefix",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_PURGE": "1"},
            [
                "the lake directory {lake} does not exist",
                "kind delete cluster --name huron-local --kubeconfig",
            ],
            id="purge-lake-gone",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_NODE_LAKE": "{base}/me"},
            ["does not show {lake} at /huron-lake"],
            id="purge-another-directory",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_NODE_LAKE": "{twin}"},
            ["does not show {lake} at /huron-lake"],
            id="purge-another-directory-with-the-same-time",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_UID": "1001"},
            ["the pods run as", "Run this script as the host user"],
            id="purge-another-user",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_UID": "11000"},
            ["the pods run as", "Run this script as the host user"],
            id="purge-user-whose-id-ends-alike",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_GID": "10000"},
            ["the pods run as", "Run this script as the host user"],
            id="purge-group-whose-id-starts-alike",
        ),
        pytest.param(
            False,
            {
                "K8S_LOCAL_PURGE": "1",
                "HOME": "{base}",
                "K8S_LOCAL_LAKE": "{base}",
                "FAKE_MOUNTS": "{base}=/huron-lake",
            },
            [ABOVE_HOME],
            id="purge-home",
        ),
        pytest.param(
            False,
            {
                "K8S_LOCAL_PURGE": "1",
                "HOME": "{base}/me",
                "K8S_LOCAL_LAKE": "{base}/me/..",
                "FAKE_MOUNTS": "{base}/me/..=/huron-lake",
            },
            [ABOVE_HOME],
            id="purge-home-parent",
        ),
        pytest.param(
            False,
            {
                "K8S_LOCAL_PURGE": "1",
                "K8S_LOCAL_LAKE": "/",
                "FAKE_MOUNTS": "/=/huron-lake",
            },
            [ABOVE_HOME],
            id="purge-root",
        ),
        pytest.param(
            False,
            {
                "K8S_LOCAL_PURGE": "1",
                "K8S_LOCAL_LAKE": "/.",
                "FAKE_MOUNTS": "/.=/huron-lake",
            },
            [ABOVE_HOME],
            id="purge-root-dot",
        ),
        pytest.param(
            False,
            {
                "K8S_LOCAL_PURGE": "1",
                "HOME": "{base}/me",
                "K8S_LOCAL_LAKE": "{base}/link",
                "FAKE_MOUNTS": "{base}/link=/huron-lake",
            },
            [ABOVE_HOME],
            id="purge-link-to-home",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_GID": "1001"},
            ["the pods run as", "Run this script as the host user"],
            id="purge-another-group",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_PURGE": "1", "FAKE_NODE_LAKE": "{file}"},
            ["the lake directory {lake} does not exist"],
            id="purge-lake-is-a-file",
        ),
        pytest.param(
            True,
            {"K8S_LOCAL_PURGE": "1", "FAKE_NODE_LAKE": "{base}/missing"},
            ["does not show {lake} at /huron-lake"],
            id="purge-node-cannot-stat",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_KUBECONFIG": "{base}/missing"},
            ["the kubeconfig {base}/missing does not exist. Set K8S_LOCAL_KUBECONFIG"],
            id="no-kubeconfig",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_KUBECONFIG": "{base}/me"},
            ["the kubeconfig {base}/me does not exist. Set K8S_LOCAL_KUBECONFIG"],
            id="kubeconfig-is-a-directory",
        ),
        pytest.param(
            False,
            {"FAKE_NODE": "node-a node-b"},
            ["the cluster must have one node, not 'node-a node-b'"],
            id="two-nodes",
        ),
        pytest.param(
            False,
            {"FAKE_NODE": ""},
            ["the cluster must have one node, not ''"],
            id="no-node",
        ),
        pytest.param(
            False,
            {"FAKE_NO_CONTAINER": "1"},
            ["is not a container of this Docker engine"],
            id="node-not-a-container",
        ),
        pytest.param(
            False,
            {"FAKE_MOUNTS": "/other{lake}=/huron-lake"},
            ["so it is not the local cluster"],
            id="node-binds-a-path-that-ends-alike",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_LAKE": "{base}/l.ke", "FAKE_MOUNTS": "{base}/lake=/huron-lake"},
            ["so it is not the local cluster"],
            id="node-binds-a-path-that-matches-as-a-pattern",
        ),
        pytest.param(
            False,
            {"K8S_LOCAL_LAKE": "-ve"},
            ["does not bind -ve at /huron-lake, so it is not the local cluster"],
            id="lake-that-grep-reads-as-options",
        ),
    ],
)
def test_down_refuses_and_deletes_nothing(
    fake_cluster: FakeCluster,
    make_lake: bool,
    changes: dict[str, str],
    messages: list[str],
) -> None:
    if make_lake:
        fake_cluster.lake.mkdir()
    base = fake_cluster.lake.parent
    (base / "me").mkdir()
    (base / "link").symlink_to(base / "me")
    if changes.get("FAKE_NODE_LAKE") == "{file}":
        fake_cluster.lake.write_text("", encoding="utf-8")
        changes = {**changes, "FAKE_NODE_LAKE": "{lake}"}
    if changes.get("FAKE_NODE_LAKE") == "{twin}":
        # Another directory on the same filesystem, with the time of the lake: only the inode
        # differs.
        (base / "twin").mkdir()
        shown = os.stat(fake_cluster.lake)
        os.utime(base / "twin", ns=(shown.st_atime_ns, shown.st_mtime_ns))
    places = {"lake": fake_cluster.lake, "base": base, "twin": base / "twin"}
    finished = fake_cluster.run("down", **{k: v.format(**places) for k, v in changes.items()})
    assert finished.returncode == 1
    for message in messages:
        assert message.format(**places) in finished.stderr
    assert not [c for c in fake_cluster.calls() if " delete " in c or c.startswith("find ")]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("0", id="zero"),
        pytest.param("yes", id="yes"),
        pytest.param("10", id="ten"),
        pytest.param("01", id="leading-zero"),
        pytest.param("1 ", id="trailing-space"),
        pytest.param(" 1", id="leading-space"),
        pytest.param("true", id="true"),
        pytest.param("", id="empty"),
    ],
)
@pytest.mark.parametrize("lake_made", [True, False], ids=["lake-made", "lake-gone"])
def test_only_the_value_1_purges(fake_cluster: FakeCluster, value: str, lake_made: bool) -> None:
    # Without a purge, down checks no lake: it also works after the lake directory is gone.
    if lake_made:
        fake_cluster.lake.mkdir()
    finished = fake_cluster.run("down", K8S_LOCAL_PURGE=value)
    assert finished.returncode == 0, finished.stderr
    assert "K8S_LOCAL_PURGE=1 deletes its content" in finished.stdout
    calls = fake_cluster.calls()
    assert [c for c in calls if " delete " in c] == [
        f"kubectl {fake_cluster.target} delete namespace huron --ignore-not-found --wait",
        f"kubectl {fake_cluster.target} delete persistentvolume huron-local-lake"
        " --ignore-not-found",
    ]
    assert not [c for c in calls if c.startswith("find ") or " rmi " in c or "image rm" in c]


def test_a_purge_empties_the_lake_that_the_node_shows(fake_cluster: FakeCluster) -> None:
    # The real find, on a lake in the temporary directory of the test.
    (fake_cluster.tools / "find").unlink()
    fake_cluster.lake.mkdir()
    (fake_cluster.lake / "helio" / "heliophysics").mkdir(parents=True)
    (fake_cluster.lake / "helio" / ".huron").write_text("{}", encoding="utf-8")
    (fake_cluster.lake / ".huron").write_text("{}", encoding="utf-8")
    finished = fake_cluster.run("down", K8S_LOCAL_PURGE="1")
    assert finished.returncode == 0, finished.stderr
    assert fake_cluster.lake.is_dir() and list(fake_cluster.lake.iterdir()) == []
    assert len([c for c in fake_cluster.calls() if " delete " in c]) == 2
    removed = [c.split()[-1] for c in fake_cluster.calls() if " crictl rmi " in c]
    assert set(removed) == LOCAL_IMAGES


def test_no_generator_reads_a_file_outside_its_directory() -> None:
    for directory in (BASE, LOCAL):
        kustomization = yaml.safe_load((ROOT / directory / "kustomization.yaml").read_text())
        assert _outside_files(kustomization) == []


def test_a_generator_that_reads_a_parent_directory_breaks_the_generator_rule() -> None:
    kustomization = yaml.safe_load((ROOT / LOCAL / "kustomization.yaml").read_text())
    kustomization["configMapGenerator"][0]["files"] = ["../../huron.dev.yaml"]
    assert _outside_files(kustomization) == ["huron-config reads ../../huron.dev.yaml"]


def _script(verb: str, *, check: bool = True, **variables: str) -> subprocess.CompletedProcess[str]:
    """Run ``scripts/k8s-local.sh verb`` with ``variables`` added to a fixed environment.

    The host's variables of the script and of the fakes, and the variables that change how bash
    starts, do not reach it. HOME is a fixed path that no lake of a test lies above, unless
    ``variables`` set them.
    """
    kept = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(SCRIPT_VARIABLES + SHELL_PREFIXES) and name not in SHELL_VARIABLES
    }
    return subprocess.run(
        [str(ROOT / "scripts/k8s-local.sh"), verb],
        capture_output=True,
        text=True,
        check=check,
        env={**kept, "HOME": TEST_HOME, **variables},
    )


def _script_settings() -> dict[str, str]:
    """The ``name=value`` lines that ``scripts/k8s-local.sh settings`` prints."""
    lines = _script("settings").stdout.splitlines()
    return dict(line.split("=", 1) for line in lines)


@cache
def _render(directory: str) -> list[Manifest]:
    """The manifests that ``kubectl kustomize`` renders from ``directory``."""
    finished = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / directory)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [m for m in yaml.safe_load_all(finished.stdout) if m]


def _name(manifest: Manifest) -> tuple[str, str]:
    return manifest["kind"], manifest["metadata"]["name"]


def _one(manifests: list[Manifest], kind: str, name: str) -> Manifest:
    (found,) = [m for m in manifests if _name(m) == (kind, name)]
    return found


def _pod(workload: Manifest) -> dict[str, Any]:
    pod: dict[str, Any] = workload["spec"]["template"]["spec"]
    return pod


def _container(workload: Manifest, name: str) -> dict[str, Any]:
    (found,) = [c for c in _pod(workload)["containers"] if c["name"] == name]
    return found


def _env(container: dict[str, Any]) -> dict[str, str]:
    return {variable["name"]: variable["value"] for variable in container.get("env", [])}


def _flag(container: dict[str, Any], name: str) -> str:
    (value,) = [a.split("=", 1)[1] for a in container["args"] if a.startswith(f"-{name}=")]
    return value


def _configmap_name(manifests: list[Manifest], prefix: str) -> str:
    (name,) = [
        m["metadata"]["name"]
        for m in manifests
        if m["kind"] == "ConfigMap" and re.fullmatch(rf"{prefix}-[a-z0-9]+", m["metadata"]["name"])
    ]
    return str(name)


def _service_configuration(manifests: list[Manifest]) -> str:
    name = _configmap_name(manifests, "huron-config")
    return str(_one(manifests, "ConfigMap", name)["data"]["huron.yaml"])


def _lake_path(manifests: list[Manifest]) -> str:
    return str(yaml.safe_load(_service_configuration(manifests))["lake_path"])


def _claim(volume: dict[str, Any]) -> str | None:
    claim: str | None = volume.get("persistentVolumeClaim", {}).get("claimName")
    return claim


def _replaced(argument: str, prefix: str, value: str) -> str:
    return prefix + value if argument.startswith(prefix) else argument


def _workloads(manifests: list[Manifest]) -> list[Manifest]:
    return [m for m in manifests if m["kind"] in WORKLOADS]


def _strategy(workload: Manifest) -> str | None:
    strategy: str | None = workload["spec"].get("strategy", {}).get("type")
    return strategy


def _writer_problems(manifests: list[Manifest]) -> list[str]:
    """One API pod writes the lake: one replica, and the old pod stops before a new one starts."""
    api = _one(manifests, "Deployment", "huron")
    problems = []
    replicas = api["spec"].get("replicas", 1)
    if replicas != 1:
        problems.append(f"the API runs {replicas} replicas, not 1")
    if _strategy(api) != "Recreate":
        problems.append("the API does not use the strategy Recreate")
    return problems


def _tusd_problems(manifests: list[Manifest]) -> list[str]:
    """One workload runs tusd. A pod that removes tusd's lock files before tusd starts runs one
    replica with the strategy Recreate, so no other tusd can hold those locks.
    """
    workloads = _workloads(manifests)
    holders = [w for w in workloads if any(c["image"] == TUSD_IMAGE for c in _pod(w)["containers"])]
    problems = [] if len(holders) == 1 else [f"{len(holders)} workloads run tusd, not 1"]
    for workload in workloads:
        name = workload["metadata"]["name"]
        initial = _pod(workload).get("initContainers", [])
        cleans = any(LOCK_CLEANUP in c.get("command", []) for c in initial)
        if workload in holders and not cleans:
            problems.append(f"{name} starts tusd with no lock cleanup before it")
        if not cleans:
            continue
        cleaner = f"{name} removes the lock files of tusd and"
        replicas = workload["spec"].get("replicas", 1)
        if workload["kind"] != "Deployment" or replicas != 1:
            problems.append(f"{cleaner} runs {replicas} replicas, not 1")
        if _strategy(workload) != "Recreate":
            problems.append(f"{cleaner} does not use the strategy Recreate")
    return problems


def _probe_problems(manifests: list[Manifest]) -> list[str]:
    """Readiness asks /readyz with a timeout of 3 s, every 5 s, and fails after 3 misses.
    Liveness asks a path that makes no call to the lake.
    """
    problems = []
    for (deployment, container), live in ((API, "/healthz"), (PROXY, "/livez")):
        found = _container(_one(manifests, "Deployment", deployment), container)
        ready = found.get("readinessProbe", {})
        shape = (
            ready.get("httpGet", {}).get("path"),
            ready.get("timeoutSeconds"),
            ready.get("periodSeconds"),
            ready.get("failureThreshold"),
        )
        if shape != ("/readyz", 3, 5, 3):
            problems.append(f"the readiness of {container} is {shape}, not ('/readyz', 3, 5, 3)")
        path = found.get("livenessProbe", {}).get("httpGet", {}).get("path")
        if path != live:
            problems.append(f"the liveness of {container} asks {path}, not {live}")
    return problems


def _grace_problems(manifests: list[Manifest], settings: Settings) -> list[str]:
    """Each pod waits longer than the longest seal (upload_hook_timeout) before it is killed, and
    tusd waits upload_hook_timeout for a hook.
    """
    limit = int(settings.upload_hook_timeout.total_seconds())
    problems = []
    for name in ("huron", "huron-uploads"):
        grace = _pod(_one(manifests, "Deployment", name)).get("terminationGracePeriodSeconds", 30)
        if grace <= limit:
            problems.append(
                f"{name} waits {grace} s before it is killed, not more than the {limit} s of a seal"
            )
    tusd = _container(_one(manifests, "Deployment", "huron-uploads"), "tusd")
    waited = _flag(tusd, "hooks-http-timeout")
    if waited != f"{limit}s":
        problems.append(
            f"tusd waits {waited.removesuffix('s')} s for a hook, not the upload_hook_timeout"
            f" of {limit} s"
        )
    return problems


def _lake_problems(manifests: list[Manifest], settings: Settings) -> list[str]:
    """Each pod that mounts the lake mounts it at lake_path, runs as the service user with its
    group, never as root and with the seccomp profile RuntimeDefault. tusd keeps its uploads in
    lake_path/.tus-uploads.
    """
    problems = []
    for workload in _workloads(manifests):
        pod, name = _pod(workload), workload["metadata"]["name"]
        claims = {v["name"] for v in pod.get("volumes", []) if _claim(v) == "huron-lake"}
        if not claims:
            continue
        problems += [
            f"{name} mounts the lake at {m['mountPath']}, not at lake_path"
            for c in pod["containers"] + pod.get("initContainers", [])
            for m in c.get("volumeMounts", [])
            if m["name"] in claims and Path(m["mountPath"]) != settings.lake_path
        ]
        context = pod["securityContext"]
        if context["runAsUser"] != settings.service_uid:
            problems.append(f"{name} runs as {context['runAsUser']}, not the service user")
        if context["runAsGroup"] not in context.get("supplementalGroups", []):
            problems.append(f"{name} does not have its group in supplementalGroups")
        if context.get("runAsNonRoot") is not True:
            problems.append(f"{name} does not refuse to run as root")
        if context.get("seccompProfile") != {"type": "RuntimeDefault"}:
            problems.append(f"{name} has no seccomp profile RuntimeDefault")
    tusd = _container(_one(manifests, "Deployment", "huron-uploads"), "tusd")
    if _flag(tusd, "upload-dir") != f"{settings.lake_path}/{UPLOAD_DIR}":
        problems.append("tusd keeps its uploads outside lake_path/.tus-uploads")
    return problems


def _proxy_problems(manifests: list[Manifest], settings: Settings) -> list[str]:
    """The proxy runs the pinned nginx through its entrypoint, forwards the authority and the
    scheme of uploads_url, and asks the API Service, which tusd calls for its hooks too.
    """
    uploads = _one(manifests, "Deployment", "huron-uploads")
    proxy, tusd = _container(uploads, "proxy"), _container(uploads, "tusd")
    problems = []
    if proxy["image"] != NGINX_IMAGE:
        problems.append(f"the proxy runs {proxy['image']}, not {NGINX_IMAGE}")
    if "command" in proxy:
        problems.append("the proxy sets command, which skips the template step")
    if proxy.get("args") != PROXY_ARGS:
        problems.append("the proxy does not start nginx with /tmp/nginx-uploads.conf")
    env = _env(proxy)
    forwarded = f"{env['HURON_UPLOADS_PROTO']}://{env['HURON_UPLOADS_HOST']}/files/"
    if forwarded != settings.uploads_url:
        problems.append(f"the proxy forwards {forwarded}, not uploads_url {settings.uploads_url}")
    (port,) = _one(manifests, "Service", "huron")["spec"]["ports"]
    api = f"huron:{port['port']}"
    hooks = f"http://{api}/api/v1/uploads/hooks"
    if env["HURON_API_UPSTREAM"] != api or _flag(tusd, "hooks-http") != hooks:
        problems.append(f"the proxy or tusd does not call the API Service {api}")
    if tusd["image"] != TUSD_IMAGE or "command" in tusd:
        problems.append(f"tusd does not run {TUSD_IMAGE} through its entrypoint")
    return problems


def _local_problems(manifests: list[Manifest]) -> list[str]:
    """The local overlay: no Route, the ingress-nginx settings of the uploads, the Job that
    prepares the lake, the identity provider in the API pod, restricted init containers, and only
    images that scripts/k8s-local.sh imports into the node, never pulled.
    """
    problems = []
    if any(m["kind"] == "Route" for m in manifests):
        problems.append("the local overlay keeps a Route, which no router serves")
    annotations = _one(manifests, "Ingress", "huron-uploads")["metadata"].get("annotations", {})
    if UPLOAD_INGRESS_ANNOTATIONS.items() - annotations.items():
        problems.append("the Ingress huron-uploads lacks the ingress-nginx settings of the uploads")
    if ("Job", "huron-lake-init") not in {_name(m) for m in manifests}:
        problems.append("the local overlay has no Job huron-lake-init")
    names = [c["name"] for c in _pod(_one(manifests, "Deployment", "huron"))["containers"]]
    if names != ["api", "keycloak", "groups"]:
        problems.append(f"the API pod holds {', '.join(names)}, not api, keycloak and groups")
    for workload in _workloads(manifests):
        pod = _pod(workload)
        for container in pod.get("initContainers", []):
            if not _restricted(pod, container):
                problems.append(f"{container['name']} is not a restricted container")
        for container in pod["containers"] + pod.get("initContainers", []):
            if container.get("imagePullPolicy") != "Never":
                problems.append(f"{container['name']} can pull its image")
            if container["image"] not in LOCAL_IMAGES:
                problems.append(
                    f"{container['name']} runs {container['image']}, which the node does not get"
                )
    return problems


def _restricted(pod: dict[str, Any], container: dict[str, Any]) -> bool:
    """Whether ``container`` runs as a user other than root, with no privilege escalation, no
    capability, a read-only root filesystem and the seccomp profile RuntimeDefault. A setting of
    the pod counts for the container where the container sets none.
    """
    context = {**pod.get("securityContext", {}), **container.get("securityContext", {})}
    return (
        context.get("runAsNonRoot") is True
        and context.get("allowPrivilegeEscalation") is False
        and context.get("readOnlyRootFilesystem") is True
        and context.get("capabilities") == {"drop": ["ALL"]}
        and context.get("seccompProfile") == {"type": "RuntimeDefault"}
    )


def _outside_files(kustomization: dict[str, Any]) -> list[str]:
    """Each file of a generator that is not in the directory of the kustomization."""
    generators = [
        *kustomization.get("configMapGenerator", []),
        *kustomization.get("secretGenerator", []),
    ]
    return [
        f"{generator['name']} reads {path}"
        for generator in generators
        for path in generator.get("files", []) + generator.get("envs", [])
        if ".." in Path(path.split("=", 1)[-1]).parts
    ]


def _replicas(manifests: list[Manifest], name: str, count: int) -> None:
    _one(manifests, "Deployment", name)["spec"]["replicas"] = count


def _rolling(manifests: list[Manifest], name: str) -> None:
    _one(manifests, "Deployment", name)["spec"]["strategy"] = {"type": "RollingUpdate"}


def _twin(manifests: list[Manifest]) -> None:
    twin = copy.deepcopy(_one(manifests, "Deployment", "huron-uploads"))
    twin["metadata"]["name"] = "huron-uploads-twin"
    manifests.append(twin)


def _no_cleanup(manifests: list[Manifest]) -> None:
    del _pod(_one(manifests, "Deployment", "huron-uploads"))["initContainers"]
