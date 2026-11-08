"""Organization places, per-organization markers, provisioning and its shell script."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from huron.core.storage import (
    MARKER_FILE,
    MARKER_MODE,
    ORGANIZATION_MODE,
    Marker,
    MarkerState,
    StorageError,
    marker_state,
    place_of,
    read_marker,
    render_marker,
    verify_marker,
)
from huron.core.storage.check import (
    ExpectedOrganization,
    Finding,
    Severity,
    check_organization,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.core.storage.provision import OrganizationTarget, Provisioner, provision_script

PREFIX = Path("/projects/huron")
ROOT = Path("/data1/huron")
INSTANCE = "id-1"


def helio_marker(instance: str = INSTANCE, organization: str | None = "helio") -> Marker:
    return Marker(1, "http://huron.test", instance, organization)


def target(root: Path = ROOT, name: str = "helio") -> OrganizationTarget:
    return OrganizationTarget(
        place_of(name, str(root), True, PREFIX), helio_marker(organization=name)
    )


def share() -> MemoryStorage:
    storage = MemoryStorage(PREFIX)
    storage.add_root(ROOT, uid=storage.uid)
    return storage


def provisioner(storage: MemoryStorage) -> Provisioner:
    return Provisioner(storage, PREFIX)


def test_an_organization_without_a_root_lives_under_the_prefix() -> None:
    place = place_of("helio", None, False, PREFIX)
    assert place.directory == PREFIX / "helio"
    assert not place.own_marker and place.marker_directory == PREFIX
    assert place.resolve("helio/sun/wind") == PREFIX / "helio" / "sun" / "wind"


def test_a_declared_organization_without_a_root_carries_its_own_marker() -> None:
    place = place_of("helio", None, True, PREFIX)
    assert place.directory == PREFIX / "helio"
    assert place.own_marker and place.marker_directory == PREFIX / "helio"


def test_an_organization_with_a_root_lives_under_it() -> None:
    place = place_of("geo", "/data2/huron/", True, PREFIX)
    assert place.base == Path("/data2/huron") and place.rooted
    assert place.directory == Path("/data2/huron/geo") == place.marker_directory
    assert place.resolve("geo/terra") == Path("/data2/huron/geo/terra")
    assert place_of("geo", "/", True, PREFIX).directory == Path("/geo")
    assert place_of("geo", None, True, PREFIX, "nfs1:/geo").export == "nfs1:/geo"
    assert place_of("geo", "/data2/huron", True, PREFIX).export is None


@pytest.mark.parametrize("root", ["data2/huron", "/data2/../etc", "/data2//huron", "/a/./b", ""])
def test_roots_that_are_not_absolute_and_normalized_are_refused(root: str) -> None:
    with pytest.raises(StorageError, match="not an absolute, normalized path"):
        place_of("geo", root, True, PREFIX)


def test_a_place_refuses_paths_of_other_organizations_and_escapes() -> None:
    place = place_of("helio", str(ROOT), True, PREFIX)
    with pytest.raises(StorageError, match="not in organization helio"):
        place.resolve("geo/terra")
    with pytest.raises(StorageError):
        place.resolve("helio/../geo")


def test_organization_markers_round_trip() -> None:
    storage = share()
    assert b'"organization"' not in render_marker(helio_marker(organization=None))
    storage.write_bytes(ROOT / MARKER_FILE, render_marker(helio_marker()))
    assert read_marker(storage, ROOT) == helio_marker()
    assert verify_marker(storage, ROOT, INSTANCE, "helio").organization == "helio"


def test_a_marker_must_name_exactly_the_expected_organization() -> None:
    storage = share()
    storage.write_bytes(ROOT / MARKER_FILE, render_marker(helio_marker()))
    with pytest.raises(StorageError, match="names organization helio, not organization geo"):
        verify_marker(storage, ROOT, INSTANCE, "geo")
    with pytest.raises(StorageError, match="names organization helio, not the share root"):
        verify_marker(storage, ROOT, INSTANCE)
    storage.write_bytes(ROOT / MARKER_FILE, render_marker(helio_marker(organization=None)))
    with pytest.raises(StorageError, match="names no organization, not organization helio"):
        verify_marker(storage, ROOT, INSTANCE, "helio")


def test_marker_states_name_every_refusal() -> None:
    storage = share()
    assert marker_state(storage, ROOT / "absent", INSTANCE, "helio") is MarkerState.MISSING
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.NO_MARKER
    storage.write_bytes(ROOT / MARKER_FILE, b"[1, 2]")
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.NO_MARKER
    storage.write_bytes(ROOT / MARKER_FILE, render_marker(helio_marker("id-2")))
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.WRONG_INSTANCE
    assert marker_state(storage, ROOT, INSTANCE, "geo") is MarkerState.WRONG_INSTANCE
    storage.write_bytes(ROOT / MARKER_FILE, render_marker(helio_marker()))
    assert marker_state(storage, ROOT, INSTANCE, "geo") is MarkerState.WRONG_ORG
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.OK
    assert str(MarkerState.WRONG_ORG) == "wrong org"


def test_provisioning_creates_the_directory_with_its_mode_and_marks_it() -> None:
    storage = share()
    steps = provisioner(storage).provision(target())
    directory = ROOT / "helio"
    assert steps == [f"created: {directory}", f"marker written: {directory / MARKER_FILE}"]
    assert storage.nodes[directory].mode == ORGANIZATION_MODE
    assert storage.nodes[directory / MARKER_FILE].mode == MARKER_MODE
    assert read_marker(storage, directory) == helio_marker()


def test_provisioning_again_changes_nothing() -> None:
    storage = share()
    provisioner(storage).provision(target())
    before = list(storage.calls)
    again = provisioner(storage).provision(target())
    assert again == [f"exists: {ROOT / 'helio'}", f"marker ok: {ROOT / 'helio' / MARKER_FILE}"]
    assert storage.calls == before


def test_provisioning_repairs_an_existing_directory_without_a_marker() -> None:
    storage = share()
    directory = ROOT / "helio"
    storage.make_directory(directory, 0o2750)
    steps = provisioner(storage).provision(target())
    assert steps == [
        f"exists: {directory}",
        f"mode set to 2751: {directory}",
        f"marker written: {directory / MARKER_FILE}",
    ]
    assert storage.nodes[directory].mode == ORGANIZATION_MODE
    assert read_marker(storage, directory).organization == "helio"


def test_a_dry_run_reports_and_changes_nothing() -> None:
    storage = share()
    directory, marker = ROOT / "helio", ROOT / "helio" / MARKER_FILE
    planned = provisioner(storage).provision(target(), dry_run=True)
    assert planned == [f"would create: {directory}", f"would write marker: {marker}"]
    assert storage.calls == [] and not storage.exists(directory)
    storage.make_directory(directory, 0o2750)
    calls = list(storage.calls)
    assert provisioner(storage).provision(target(), dry_run=True) == [
        f"exists: {directory}",
        f"would set mode 2751: {directory}",
        f"would write marker: {marker}",
    ]
    assert storage.calls == calls
    provisioner(storage).provision(target())
    again = provisioner(storage).provision(target(), dry_run=True)
    assert again == [f"exists: {directory}", f"marker ok: {marker}"]


def test_the_root_itself_is_never_created() -> None:
    storage = share()
    with pytest.raises(StorageError, match="The storage admin creates it"):
        provisioner(storage).provision(target(Path("/data2/huron"), "geo"))
    with pytest.raises(StorageError, match="does not exist"):
        provisioner(storage).provision(target(Path("/data2/huron"), "geo"), dry_run=True)
    assert not storage.exists(Path("/data2/huron"))


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (render_marker(helio_marker("id-2")), "names service id-2 and organization helio"),
        (
            render_marker(helio_marker(organization="geo")),
            "names service id-1 and organization geo",
        ),
        (render_marker(helio_marker(organization=None)), "and organization (none)"),
        (b"{broken", "is unreadable"),
    ],
)
def test_a_foreign_marker_is_never_overwritten(data: bytes, reason: str) -> None:
    storage = share()
    storage.make_directory(ROOT / "helio", 0o2750)
    storage.write_bytes(ROOT / "helio" / MARKER_FILE, data)
    before = list(storage.calls)
    for dry_run in (False, True):
        with pytest.raises(StorageError, match="Huron does not overwrite it") as refused:
            provisioner(storage).provision(target(), dry_run=dry_run)
        assert reason in refused.value.message
    assert storage.calls == before and storage.nodes[ROOT / "helio"].mode == 0o2750
    assert storage.read_bytes(ROOT / "helio" / MARKER_FILE) == data


def test_provisioning_a_directory_owned_by_someone_else_fails_cleanly() -> None:
    storage = share()
    storage.add_root(ROOT / "helio", uid=0)
    with pytest.raises(StorageError, match="permission denied"):
        provisioner(storage).provision(target())
    assert not storage.exists(ROOT / "helio" / MARKER_FILE)


def test_the_lake_path_gets_the_marker_of_the_service() -> None:
    storage = share()
    marker = PREFIX / MARKER_FILE
    lake = helio_marker(organization=None)
    assert provisioner(storage).mark_lake(lake, dry_run=True) == [f"would write marker: {marker}"]
    assert storage.calls == [] and not storage.exists(marker)
    assert provisioner(storage).mark_lake(lake) == [f"marker written: {marker}"]
    assert read_marker(storage, PREFIX) == lake
    assert storage.nodes[marker].mode == MARKER_MODE
    assert provisioner(storage).mark_lake(lake) == [f"marker ok: {marker}"]
    assert provisioner(storage).mark_lake(lake, dry_run=True) == [f"marker ok: {marker}"]


def test_the_lake_path_marker_is_never_overwritten_and_the_path_never_created() -> None:
    storage = share()
    storage.write_bytes(PREFIX / MARKER_FILE, render_marker(helio_marker()))
    with pytest.raises(StorageError, match="names service id-1 and organization helio"):
        provisioner(storage).mark_lake(helio_marker(organization=None))
    with pytest.raises(StorageError, match="the lake path /lake does not exist"):
        Provisioner(storage, Path("/lake")).mark_lake(helio_marker(organization=None))
    assert not storage.exists(Path("/lake"))


def test_the_script_does_what_provisioning_does() -> None:
    script = provision_script(PREFIX, helio_marker(organization=None), [target()])
    lake, helio = f"{PREFIX / MARKER_FILE}", f"{ROOT / 'helio'}"
    service = """'"instance_id": "id-1"'"""
    rendered = render_marker(helio_marker(organization=None)).decode().rstrip()
    assert script.splitlines() == [
        "#!/bin/sh",
        "# Prepare the Huron lake path and organization directories:"
        " huron adm provision-orgs --emit-script.",
        "# Run as a user that may write the lake path and each root (or as root)."
        " Running it again is harmless.",
        "set -eu",
        "",
        f"# lake path {PREFIX}",
        f"test -d {PREFIX} || {{",
        f"  printf 'error: the lake path %s does not exist\\n' {PREFIX} >&2; exit 1; }}",
        f"if [ -e {lake} ]; then",
        f"  grep -qF {service} {lake} && ! grep -qF '\"organization\"' {lake} || {{",
        f"    printf 'error: %s names another service or organization\\n' {lake} >&2; exit 1; }}",
        "fi",
        f"[ -e {lake} ] || printf '%s\\n' '{rendered}' > {lake}",
        f"chmod 644 {lake}",
        "",
        "# organization helio",
        f"test -d {ROOT} || {{",
        f"  printf 'error: the root %s does not exist\\n' {ROOT} >&2; exit 1; }}",
        f"if [ -e {helio}/.huron ]; then",
        f"  grep -qF {service} {helio}/.huron"
        f' && grep -qF \'"organization": "helio"\' {helio}/.huron || {{',
        f"    printf 'error: %s names another service or organization\\n' {helio}/.huron >&2;"
        " exit 1; }",
        "fi",
        f"[ -d {helio} ] || mkdir {helio}",
        f"chmod 2751 {helio}",
        f"[ -e {helio}/.huron ] || printf '%s\\n'"
        f" '{render_marker(helio_marker()).decode().rstrip()}' > {helio}/.huron",
        f"chmod 644 {helio}/.huron",
    ]
    checked = subprocess.run(["sh", "-n"], input=script, text=True, check=False)
    assert checked.returncode == 0


def run_script(path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(path)], capture_output=True, text=True, check=False, cwd=cwd)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_script_runs_and_is_idempotent(tmp_path: Path) -> None:
    lake, root = tmp_path / "lake", tmp_path / "root"
    lake.mkdir()
    root.mkdir()
    organization = OrganizationTarget(place_of("helio", str(root), True, lake), helio_marker())
    script = tmp_path / "provision.sh"
    script.write_text(provision_script(lake, helio_marker(organization=None), [organization]))
    for _ in range(2):
        done = run_script(script, tmp_path)
        assert done.returncode == 0, done.stderr
    directory = root / "helio"
    assert stat.S_IMODE(os.lstat(directory).st_mode) == ORGANIZATION_MODE
    assert stat.S_IMODE(os.lstat(directory / MARKER_FILE).st_mode) == MARKER_MODE
    storage = PosixStorage()
    assert verify_marker(storage, directory, INSTANCE, "helio") == helio_marker()
    assert verify_marker(storage, lake, INSTANCE) == helio_marker(organization=None)
    (directory / MARKER_FILE).write_text(json.dumps({"instance_id": "other"}))
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1 and "names another service" in refused.stderr
    shutil.rmtree(root)
    missing = run_script(script, tmp_path)
    assert missing.returncode == 1 and f"the root {root} does not exist" in missing.stderr
    (lake / MARKER_FILE).write_bytes(render_marker(helio_marker()))
    named = run_script(script, tmp_path)
    assert named.returncode == 1 and f"{lake}/.huron names another" in named.stderr
    shutil.rmtree(lake)
    gone = run_script(script, tmp_path)
    assert gone.returncode == 1 and f"the lake path {lake} does not exist" in gone.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_script_never_expands_a_path(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    root = tmp_path / "$(touch pwned)`touch pwned`"
    organization = OrganizationTarget(place_of("helio", str(root), True, lake), helio_marker())
    script = tmp_path / "provision.sh"
    script.write_text(provision_script(lake, helio_marker(organization=None), [organization]))
    missing = run_script(script, tmp_path)
    assert missing.returncode == 1 and f"the root {root} does not exist" in missing.stderr
    root.mkdir()
    (root / "helio").mkdir()
    (root / "helio" / MARKER_FILE).write_text(json.dumps({"instance_id": "other"}))
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1 and f"{root}/helio/.huron names another" in refused.stderr
    assert not (tmp_path / "pwned").exists()


def test_posix_storage_writes_files_with_the_mode_asked_for(tmp_path: Path) -> None:
    storage = PosixStorage()
    storage.write_bytes(tmp_path / "m", b"x", MARKER_MODE)
    assert stat.S_IMODE(os.lstat(tmp_path / "m").st_mode) == MARKER_MODE
    memory = MemoryStorage(tmp_path)
    memory.write_bytes(tmp_path / "plain", b"x")
    assert memory.nodes[tmp_path / "plain"].mode == 0o660


def expected(storage: MemoryStorage, own_marker: bool = True) -> list[Finding]:
    organization = ExpectedOrganization("helio", ROOT / "helio", INSTANCE, own_marker)
    return check_organization(storage, organization)


def test_organization_findings() -> None:
    storage = share()
    missing = expected(storage)
    assert [(f.code, f.severity, f.path) for f in missing] == [
        ("org_dir_missing", Severity.ERROR, str(ROOT / "helio"))
    ]
    provisioner(storage).provision(target())
    assert expected(storage) == []
    storage.remove_file(ROOT / "helio" / MARKER_FILE)
    assert [f.code for f in expected(storage)] == ["org_marker_missing"]
    assert expected(storage, own_marker=False) == []
    storage.write_bytes(ROOT / "helio" / MARKER_FILE, render_marker(helio_marker("id-2")))
    mismatch = expected(storage)
    assert [(f.code, f.detail) for f in mismatch] == [("org_marker_mismatch", "wrong instance")]
