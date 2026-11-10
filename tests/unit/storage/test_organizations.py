"""Organization places, per-organization markers, provisioning and its shell script."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    MARKER_FILE,
    MARKER_MODE,
    ORGANIZATION_MODE,
    LakePath,
    Marker,
    MarkerState,
    OrganizationPlace,
    StorageError,
    marker_state,
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
from huron.core.storage.provision import (
    OrganizationTarget,
    Provisioner,
    absolute,
    provision_script,
)
from huron.pkg.errors import HuronError

PREFIX = "/projects/huron"
#: The root of the declared organizations, below the lake path.
ROOT = LakePath.of("data1")
HELIO = ROOT.joinpath("helio")
INSTANCE = "id-1"


def shown(location: LakePath) -> str:
    """Where ``location`` is on this machine."""
    return absolute(PREFIX, location)


def helio_marker(instance: str = INSTANCE, organization: str | None = "helio") -> Marker:
    return Marker(1, "http://huron.test", instance, organization)


def target(root: LakePath = ROOT, name: str = "helio") -> OrganizationTarget:
    return OrganizationTarget(
        OrganizationPlace(name, root, own_marker=True), helio_marker(organization=name)
    )


def share() -> MemoryStorage:
    storage = MemoryStorage(Path(PREFIX))
    storage.add_directory(ROOT, uid=storage.uid)
    return storage


def provisioner(storage: MemoryStorage) -> Provisioner:
    return Provisioner(storage, PREFIX)


def test_an_organization_without_its_own_marker_shares_the_marker_at_its_base() -> None:
    place = OrganizationPlace("helio", LakePath(), own_marker=False)
    assert place.directory == LakePath.of("helio")
    assert place.marker_directory == LakePath()
    assert place.locate("helio/sun/wind") == LakePath.of("helio", "sun", "wind")


def test_an_organization_with_its_own_marker_lives_below_its_root() -> None:
    place = OrganizationPlace("geo", LakePath.of("data2"), own_marker=True)
    assert place.directory == LakePath.of("data2", "geo") == place.marker_directory
    assert place.locate("geo/terra") == LakePath.of("data2", "geo", "terra")


def test_absolute_names_a_lake_path_on_this_machine() -> None:
    assert absolute("/lake/", LakePath.of("a", "b")) == "/lake/a/b"
    assert absolute("/lake", LakePath()) == "/lake"


@pytest.mark.parametrize("api_path", ["geo/terra", "helio/../geo", "", "helio//x"])
def test_a_place_refuses_paths_of_other_organizations_and_escapes(api_path: str) -> None:
    place = OrganizationPlace("helio", ROOT, own_marker=True)
    with pytest.raises(HuronError) as refused:
        place.locate(api_path)
    assert (refused.value.code, refused.value.context["rule"]) == ("NAME_INVALID", "lake_name")


def test_each_directory_of_an_organization_has_its_mode() -> None:
    place = OrganizationPlace("helio", ROOT, own_marker=True)
    assert place.mode_of(HELIO) == ORGANIZATION_MODE
    assert place.mode_of(HELIO.joinpath("cat")) == DIRECTORY_MODE
    assert place.mode_of(HELIO.joinpath("cat", "ns", "run7")) == DIRECTORY_MODE
    with pytest.raises(ValueError, match="not below"):
        place.mode_of(LakePath.of("geo"))


def write(storage: MemoryStorage, location: LakePath, data: bytes) -> None:
    storage.write_bytes(location, data, 0o644)


def test_organization_markers_round_trip() -> None:
    storage = share()
    assert b'"organization"' not in render_marker(helio_marker(organization=None))
    write(storage, ROOT.joinpath(MARKER_FILE), render_marker(helio_marker()))
    assert read_marker(storage, ROOT) == helio_marker()
    assert verify_marker(storage, ROOT, INSTANCE, "helio").organization == "helio"


def test_a_marker_must_name_exactly_the_expected_organization() -> None:
    storage = share()
    write(storage, ROOT.joinpath(MARKER_FILE), render_marker(helio_marker()))
    with pytest.raises(StorageError, match="names organization helio, not organization geo"):
        verify_marker(storage, ROOT, INSTANCE, "geo")
    with pytest.raises(StorageError, match="names organization helio, not the lake path"):
        verify_marker(storage, ROOT, INSTANCE)
    write(storage, ROOT.joinpath(MARKER_FILE), render_marker(helio_marker(organization=None)))
    with pytest.raises(StorageError, match="names no organization, not organization helio"):
        verify_marker(storage, ROOT, INSTANCE, "helio")


def test_marker_states_name_every_refusal() -> None:
    storage = share()
    assert marker_state(storage, ROOT.joinpath("absent"), INSTANCE, "helio") is MarkerState.MISSING
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.NO_MARKER
    write(storage, ROOT.joinpath(MARKER_FILE), b"[1, 2]")
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.NO_MARKER
    write(storage, ROOT.joinpath(MARKER_FILE), render_marker(helio_marker("id-2")))
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.WRONG_INSTANCE
    assert marker_state(storage, ROOT, INSTANCE, "geo") is MarkerState.WRONG_INSTANCE
    write(storage, ROOT.joinpath(MARKER_FILE), render_marker(helio_marker()))
    assert marker_state(storage, ROOT, INSTANCE, "geo") is MarkerState.WRONG_ORG
    assert marker_state(storage, ROOT, INSTANCE, "helio") is MarkerState.OK
    assert str(MarkerState.WRONG_ORG) == "wrong org"


def test_a_marker_state_raises_a_refusal_that_is_no_marker_state() -> None:
    storage = share()
    storage.symlink(ROOT.joinpath("link"), "/outside")
    with pytest.raises(StorageError) as refused:
        marker_state(storage, ROOT.joinpath("link"), INSTANCE, "helio")
    assert refused.value.code == "SYMLINK_IN_LAKE"


def test_provisioning_creates_the_directory_with_its_mode_and_marks_it() -> None:
    storage = share()
    steps = provisioner(storage).provision(target())
    marker = HELIO.joinpath(MARKER_FILE)
    assert steps == [f"created: {shown(HELIO)}", f"marker written: {shown(marker)}"]
    assert steps[0] == "created: /projects/huron/data1/helio"
    assert storage.nodes[HELIO].mode == ORGANIZATION_MODE
    assert storage.nodes[marker].mode == MARKER_MODE
    assert read_marker(storage, HELIO) == helio_marker()


def test_provisioning_again_changes_nothing() -> None:
    storage = share()
    provisioner(storage).provision(target())
    before = list(storage.calls)
    again = provisioner(storage).provision(target())
    marker = HELIO.joinpath(MARKER_FILE)
    assert again == [f"exists: {shown(HELIO)}", f"marker ok: {shown(marker)}"]
    assert storage.calls == before


def test_provisioning_repairs_an_existing_directory_without_a_marker() -> None:
    storage = share()
    storage.make_directory(HELIO, 0o2750)
    steps = provisioner(storage).provision(target())
    assert steps == [
        f"exists: {shown(HELIO)}",
        f"mode set to 2751: {shown(HELIO)}",
        f"marker written: {shown(HELIO.joinpath(MARKER_FILE))}",
    ]
    assert storage.nodes[HELIO].mode == ORGANIZATION_MODE
    assert read_marker(storage, HELIO).organization == "helio"


def test_a_dry_run_reports_and_changes_nothing() -> None:
    storage = share()
    directory, marker = shown(HELIO), shown(HELIO.joinpath(MARKER_FILE))
    planned = provisioner(storage).provision(target(), dry_run=True)
    assert planned == [f"would create: {directory}", f"would write marker: {marker}"]
    assert storage.calls == [] and storage.stat(HELIO) is None
    storage.make_directory(HELIO, 0o2750)
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
    geo = target(LakePath.of("data2"), "geo")
    with pytest.raises(StorageError, match="the root /projects/huron/data2 of organization geo"):
        provisioner(storage).provision(geo)
    with pytest.raises(StorageError, match="The storage admin creates it"):
        provisioner(storage).provision(geo, dry_run=True)
    assert storage.stat(LakePath.of("data2")) is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (render_marker(helio_marker("id-2")), "names service id-2 and organization helio"),
        (
            render_marker(helio_marker(organization="geo")),
            "names service id-1 and organization geo",
        ),
        (
            render_marker(helio_marker(organization=None)),
            "names service id-1 and organization (none)",
        ),
        (b"{broken", "is unreadable"),
    ],
)
def test_a_foreign_marker_is_never_overwritten(data: bytes, reason: str) -> None:
    storage = share()
    storage.make_directory(HELIO, 0o2750)
    write(storage, HELIO.joinpath(MARKER_FILE), data)
    before = list(storage.calls)
    for dry_run in (False, True):
        with pytest.raises(StorageError) as refused:
            provisioner(storage).provision(target(), dry_run=dry_run)
        marker = shown(HELIO.joinpath(MARKER_FILE))
        assert refused.value.message == f"{marker} {reason}. Huron does not overwrite it"
        assert refused.value.context["path"] == shown(HELIO)
    assert storage.calls == before and storage.nodes[HELIO].mode == 0o2750
    assert storage.read_bytes(HELIO.joinpath(MARKER_FILE)) == data


def test_provisioning_a_directory_owned_by_someone_else_fails_cleanly() -> None:
    storage = share()
    storage.add_directory(HELIO, uid=0)
    with pytest.raises(StorageError, match="permission denied"):
        provisioner(storage).provision(target())
    assert storage.stat(HELIO.joinpath(MARKER_FILE)) is None


def test_the_lake_path_gets_the_marker_of_the_service() -> None:
    storage = share()
    marker, location = shown(LakePath.of(MARKER_FILE)), LakePath.of(MARKER_FILE)
    lake = helio_marker(organization=None)
    assert provisioner(storage).mark_lake(lake, dry_run=True) == [f"would write marker: {marker}"]
    assert storage.calls == [] and storage.stat(location) is None
    assert provisioner(storage).mark_lake(lake) == [f"marker written: {marker}"]
    assert marker == "/projects/huron/.huron"
    assert read_marker(storage, LakePath()) == lake
    assert storage.nodes[location].mode == MARKER_MODE
    assert provisioner(storage).mark_lake(lake) == [f"marker ok: {marker}"]
    assert provisioner(storage).mark_lake(lake, dry_run=True) == [f"marker ok: {marker}"]


def test_the_lake_path_marker_is_never_overwritten_and_the_path_never_created(
    tmp_path: Path,
) -> None:
    storage = share()
    write(storage, LakePath.of(MARKER_FILE), render_marker(helio_marker()))
    with pytest.raises(StorageError, match="names service id-1 and organization helio"):
        provisioner(storage).mark_lake(helio_marker(organization=None))
    missing = PosixStorage(tmp_path / "lake")
    with pytest.raises(StorageError, match=f"the lake path {tmp_path / 'lake'} does not exist"):
        Provisioner(missing, str(tmp_path / "lake")).mark_lake(helio_marker(organization=None))
    assert not (tmp_path / "lake").exists()


def test_a_root_that_is_a_file_is_refused_as_missing() -> None:
    storage = share()
    write(storage, LakePath.of("file"), b"")
    with pytest.raises(StorageError, match="does not exist"):
        provisioner(storage).provision(target(LakePath.of("file")))


def test_the_script_does_what_provisioning_does() -> None:
    script = provision_script(PREFIX, helio_marker(organization=None), [target()])
    lake, helio, root = f"{PREFIX}/{MARKER_FILE}", shown(HELIO), shown(ROOT)
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
        f"test -d {root} || {{",
        f"  printf 'error: the root %s does not exist\\n' {root} >&2; exit 1; }}",
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
    lake = tmp_path / "lake"
    root = lake / "root"
    root.mkdir(parents=True)
    organization = target(LakePath.of("root"))
    script = tmp_path / "provision.sh"
    script.write_text(provision_script(str(lake), helio_marker(organization=None), [organization]))
    for _ in range(2):
        done = run_script(script, tmp_path)
        assert done.returncode == 0, done.stderr
    directory = root / "helio"
    assert stat.S_IMODE(os.lstat(directory).st_mode) == ORGANIZATION_MODE
    assert stat.S_IMODE(os.lstat(directory / MARKER_FILE).st_mode) == MARKER_MODE
    storage = PosixStorage(lake)
    assert verify_marker(storage, LakePath.of("root", "helio"), INSTANCE, "helio") == helio_marker()
    assert verify_marker(storage, LakePath(), INSTANCE) == helio_marker(organization=None)
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
    name = "$(touch pwned)`touch pwned`"
    root = lake / name
    organization = target(LakePath.of(name))
    script = tmp_path / "provision.sh"
    script.write_text(provision_script(str(lake), helio_marker(organization=None), [organization]))
    missing = run_script(script, tmp_path)
    assert missing.returncode == 1 and f"the root {root} does not exist" in missing.stderr
    root.mkdir()
    (root / "helio").mkdir()
    (root / "helio" / MARKER_FILE).write_text(json.dumps({"instance_id": "other"}))
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1 and f"{root}/helio/.huron names another" in refused.stderr
    assert not (tmp_path / "pwned").exists()


def test_posix_storage_writes_files_with_the_mode_asked_for(tmp_path: Path) -> None:
    storage = PosixStorage(tmp_path)
    storage.write_bytes(LakePath.of("m"), b"x", MARKER_MODE)
    assert stat.S_IMODE(os.lstat(tmp_path / "m").st_mode) == MARKER_MODE


def expected(storage: MemoryStorage, own_marker: bool = True) -> list[Finding]:
    organization = ExpectedOrganization("helio", HELIO, INSTANCE, own_marker)
    return check_organization(storage, organization)


def test_organization_findings() -> None:
    storage = share()
    missing = expected(storage)
    assert [(f.code, f.severity, f.path) for f in missing] == [
        ("org_dir_missing", Severity.ERROR, "data1/helio")
    ]
    provisioner(storage).provision(target())
    assert expected(storage) == []
    storage.remove_file(HELIO.joinpath(MARKER_FILE))
    assert [(f.code, f.path) for f in expected(storage)] == [
        ("org_marker_missing", "data1/helio/.huron")
    ]
    assert expected(storage, own_marker=False) == []
    write(storage, HELIO.joinpath(MARKER_FILE), render_marker(helio_marker("id-2")))
    mismatch = expected(storage)
    assert [(f.code, f.detail) for f in mismatch] == [("org_marker_mismatch", "wrong instance")]
