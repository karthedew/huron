"""Organization places, per-organization markers, provisioning and its shell script."""

import errno
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    MARKER_FILE,
    MARKER_MODE,
    OBJECT_DIR,
    OBJECT_DIR_MODE,
    ORGANIZATION_MODE,
    UPLOAD_DIR,
    UPLOAD_DIR_MODE,
    UPLOADS,
    LakePath,
    Marker,
    MarkerState,
    OrganizationPlace,
    PermissionDenied,
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
    Owner,
    Provisioner,
    absolute,
    provision_script,
)
from huron.pkg.errors import HuronError
from tests.support.clock import START
from tests.support.shell import NEEDS_SHELL

PREFIX = "/projects/huron"
#: The root of the declared organizations, below the lake path.
ROOT = LakePath.of("data1")
HELIO = ROOT.joinpath("helio")
OBJECTS = HELIO.joinpath(OBJECT_DIR)
INSTANCE = "id-1"
#: The service owner: the user and the group of the in-memory lake's caller.
OWNER = Owner(1000, 1000)


def shown(location: LakePath) -> str:
    """Where ``location`` is on this machine."""
    return absolute(PREFIX, location)


def helio_marker(instance: str = INSTANCE, organization: str | None = "helio") -> Marker:
    return Marker(1, "http://huron.test", instance, organization)


def target(root: LakePath = ROOT, name: str = "helio", owner: Owner = OWNER) -> OrganizationTarget:
    return OrganizationTarget(
        OrganizationPlace(name, root, own_marker=True), helio_marker(organization=name), owner
    )


def share() -> MemoryStorage:
    """The lake path, which the caller owns, with the root ``data1`` of the organizations."""
    storage = MemoryStorage(Path(PREFIX))
    lake = storage.nodes[LakePath()]
    lake.uid, lake.gid = storage.uid, storage.gid
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


def test_owner_is_shown_in_the_numeric_form_of_chown() -> None:
    assert str(Owner(1000700000, 1000700001)) == "1000700000:1000700001"


def test_provisioning_creates_the_directory_and_its_object_area_and_marks_it() -> None:
    storage = share()
    steps = provisioner(storage).provision(target())
    marker = HELIO.joinpath(MARKER_FILE)
    assert steps == [
        f"created: {shown(HELIO)}",
        f"created: {shown(OBJECTS)}",
        f"marker written: {shown(marker)}",
    ]
    assert steps[0] == "created: /projects/huron/data1/helio"
    assert storage.nodes[HELIO].mode == ORGANIZATION_MODE
    assert storage.nodes[OBJECTS].mode == OBJECT_DIR_MODE
    assert (storage.nodes[OBJECTS].uid, storage.nodes[OBJECTS].gid) == (1000, 1000)
    assert storage.nodes[marker].mode == MARKER_MODE
    assert read_marker(storage, HELIO) == helio_marker()


def test_provisioning_again_changes_nothing() -> None:
    storage = share()
    provisioner(storage).provision(target())
    before = list(storage.calls)
    again = provisioner(storage).provision(target())
    marker = HELIO.joinpath(MARKER_FILE)
    assert again == [
        f"exists: {shown(HELIO)}",
        f"exists: {shown(OBJECTS)}",
        f"marker ok: {shown(marker)}",
    ]
    assert storage.calls == before


def test_provisioning_repairs_an_existing_directory_without_a_marker() -> None:
    storage = share()
    storage.make_directory(HELIO, 0o2750)
    storage.make_directory(OBJECTS, 0o750)
    steps = provisioner(storage).provision(target())
    assert steps == [
        f"exists: {shown(HELIO)}",
        f"mode set to 2751: {shown(HELIO)}",
        f"exists: {shown(OBJECTS)}",
        f"mode set to 700: {shown(OBJECTS)}",
        f"marker written: {shown(HELIO.joinpath(MARKER_FILE))}",
    ]
    assert storage.nodes[HELIO].mode == ORGANIZATION_MODE
    assert read_marker(storage, HELIO).organization == "helio"


def test_provisioning_as_root_gives_the_service_its_directories() -> None:
    storage = share()
    storage.uid = storage.gid = 0
    steps = provisioner(storage).provision(target(owner=Owner(7, 8)))
    assert steps == [
        f"created: {shown(HELIO)}",
        f"owner set to 7:8: {shown(HELIO)}",
        f"created: {shown(OBJECTS)}",
        f"owner set to 7:8: {shown(OBJECTS)}",
        f"marker written: {shown(HELIO.joinpath(MARKER_FILE))}",
    ]
    for location, mode in ((HELIO, ORGANIZATION_MODE), (OBJECTS, OBJECT_DIR_MODE)):
        node = storage.nodes[location]
        assert (node.uid, node.gid, node.mode) == (7, 8, mode)
    assert storage.nodes[ROOT].uid == 1000


def test_a_dry_run_reports_and_changes_nothing() -> None:
    storage = share()
    directory, marker = shown(HELIO), shown(HELIO.joinpath(MARKER_FILE))
    planned = provisioner(storage).provision(target(), dry_run=True)
    assert planned == [
        f"would create with owner 1000:1000 and mode 2751: {directory}",
        f"would create with owner 1000:1000 and mode 700: {shown(OBJECTS)}",
        f"would write marker: {marker}",
    ]
    assert storage.calls == [] and storage.stat(HELIO) is None
    storage.make_directory(HELIO, 0o2750)
    storage.make_directory(OBJECTS, OBJECT_DIR_MODE)
    calls = list(storage.calls)
    assert provisioner(storage).provision(target(owner=Owner(7, 1000)), dry_run=True) == [
        f"exists: {directory}",
        f"would set owner 7:1000: {directory}",
        f"would set mode 2751: {directory}",
        f"exists: {shown(OBJECTS)}",
        f"would set owner 7:1000: {shown(OBJECTS)}",
        f"would write marker: {marker}",
    ]
    assert storage.calls == calls
    provisioner(storage).provision(target())
    again = provisioner(storage).provision(target(), dry_run=True)
    assert again == [f"exists: {directory}", f"exists: {shown(OBJECTS)}", f"marker ok: {marker}"]


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
    with pytest.raises(PermissionDenied) as refused:
        provisioner(storage).provision(target())
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {shown(HELIO)}",
        {"path": shown(HELIO), "error": os.strerror(errno.EPERM)},
    )
    assert storage.stat(HELIO.joinpath(MARKER_FILE)) is None
    assert storage.stat(OBJECTS) is None


@pytest.mark.parametrize("dry_run", [False, True], ids=["run", "dry_run"])
def test_a_root_that_cannot_be_searched_is_named_by_its_path_on_this_machine(
    dry_run: bool,
) -> None:
    storage = share()
    storage.unreadable.add(ROOT)
    inner = ROOT.joinpath("inner")
    with pytest.raises(PermissionDenied) as refused:
        provisioner(storage).provision(target(inner), dry_run=dry_run)
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {shown(inner)}",
        {"path": shown(inner), "error": os.strerror(errno.EACCES)},
    )
    assert storage.calls == []


def test_a_posix_root_that_cannot_be_searched_is_named_by_its_path_on_this_machine(
    tmp_path: Path, temporary_mode: Callable[[Path, int], None]
) -> None:
    (tmp_path / "data1" / "inner").mkdir(parents=True)
    temporary_mode(tmp_path / "data1", 0o000)
    inner = ROOT.joinpath("inner")
    with pytest.raises(PermissionDenied) as refused:
        Provisioner(PosixStorage(tmp_path), PREFIX).provision(target(inner))
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {shown(inner)}",
        {"path": shown(inner), "error": os.strerror(errno.EACCES)},
    )


def test_a_lake_path_that_refuses_the_owner_is_named_by_its_path_on_this_machine() -> None:
    storage = share()
    with pytest.raises(PermissionDenied) as refused:
        provisioner(storage).prepare_lake(helio_marker(organization=None), Owner(7, 1000))
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {PREFIX}",
        {"path": PREFIX, "error": os.strerror(errno.EPERM)},
    )
    assert storage.stat(UPLOADS) is None


def test_a_lake_path_that_cannot_be_searched_is_named_by_its_path_on_this_machine() -> None:
    storage = share()
    storage.unreadable.add(LakePath())
    with pytest.raises(PermissionDenied) as refused:
        provisioner(storage).prepare_lake(helio_marker(organization=None), OWNER)
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {PREFIX}",
        {"path": PREFIX, "error": os.strerror(errno.EACCES)},
    )
    assert storage.calls == []


def test_an_object_area_that_is_a_file_fails_the_organization() -> None:
    storage = share()
    storage.make_directory(HELIO, ORGANIZATION_MODE)
    write(storage, OBJECTS, b"")
    with pytest.raises(StorageError) as refused:
        provisioner(storage).provision(target())
    assert type(refused.value) is StorageError
    assert refused.value.message == f"{OBJECTS}: {os.strerror(errno.EEXIST)}"
    assert storage.stat(HELIO.joinpath(MARKER_FILE)) is None


def test_the_lake_path_gets_its_owner_mode_upload_directory_and_marker() -> None:
    storage = share()
    marker, location = shown(LakePath.of(MARKER_FILE)), LakePath.of(MARKER_FILE)
    lake = helio_marker(organization=None)
    uploads = shown(UPLOADS)
    assert provisioner(storage).prepare_lake(lake, OWNER, dry_run=True) == [
        f"would set mode 2751: {PREFIX}",
        f"would create with owner 1000:1000 and mode 700: {uploads}",
        f"would write marker: {marker}",
    ]
    assert storage.calls == [] and storage.stat(location) is None
    assert provisioner(storage).prepare_lake(lake, OWNER) == [
        f"mode set to 2751: {PREFIX}",
        f"created: {uploads}",
        f"marker written: {marker}",
    ]
    assert (marker, uploads) == ("/projects/huron/.huron", f"/projects/huron/{UPLOAD_DIR}")
    assert read_marker(storage, LakePath()) == lake
    assert storage.nodes[location].mode == MARKER_MODE
    assert storage.nodes[UPLOADS].mode == UPLOAD_DIR_MODE
    assert storage.nodes[LakePath()].mode == ORGANIZATION_MODE
    assert provisioner(storage).prepare_lake(lake, OWNER) == [
        f"exists: {uploads}",
        f"marker ok: {marker}",
    ]
    assert provisioner(storage).prepare_lake(lake, Owner(7, 1000), dry_run=True) == [
        f"would set owner 7:1000: {PREFIX}",
        f"exists: {uploads}",
        f"would set owner 7:1000: {uploads}",
        f"marker ok: {marker}",
    ]


def test_the_lake_path_marker_is_never_overwritten_and_the_path_never_created(
    tmp_path: Path,
) -> None:
    storage = share()
    write(storage, LakePath.of(MARKER_FILE), render_marker(helio_marker()))
    with pytest.raises(StorageError, match="names service id-1 and organization helio"):
        provisioner(storage).prepare_lake(helio_marker(organization=None), OWNER)
    assert storage.stat(UPLOADS) is None
    missing = PosixStorage(tmp_path / "lake")
    with pytest.raises(StorageError, match=f"the lake path {tmp_path / 'lake'} does not exist"):
        Provisioner(missing, str(tmp_path / "lake")).prepare_lake(
            helio_marker(organization=None), OWNER
        )
    assert not (tmp_path / "lake").exists()


def test_a_root_that_is_a_file_is_refused_as_missing() -> None:
    storage = share()
    write(storage, LakePath.of("file"), b"")
    with pytest.raises(StorageError, match="does not exist"):
        provisioner(storage).provision(target(LakePath.of("file")))


def no_link(path: str) -> str:
    """The line of the script that refuses a symbolic link at ``path``."""
    return f"[ ! -L {path} ] || {{ printf 'error: %s is a symbolic link\\n' {path} >&2; exit 1; }}"


def made(path: str, mode: str) -> list[str]:
    """The lines of the script that make the directory ``path`` for the service owner."""
    return [
        no_link(path),
        f"[ -d {path} ] || mkdir {path}",
        f"chown 1000:1000 {path}",
        f"chmod {mode} {path}",
    ]


@NEEDS_SHELL
def test_the_script_does_what_provisioning_does() -> None:
    script = provision_script(PREFIX, helio_marker(organization=None), OWNER, [target()])
    lake, helio, root = f"{PREFIX}/{MARKER_FILE}", shown(HELIO), shown(ROOT)
    service = """'"instance_id": "id-1"'"""
    rendered = render_marker(helio_marker(organization=None)).decode().rstrip()
    assert script.splitlines() == [
        "#!/bin/sh",
        "# Prepare the Huron lake path and organization directories:"
        " huron adm provision-orgs --emit-script.",
        "# Run it as root: it changes the owner of each directory. Running it again is harmless.",
        "set -eu",
        "",
        f"# lake path {PREFIX}",
        f"test -d {PREFIX} || {{",
        f"  printf 'error: the lake path %s does not exist\\n' {PREFIX} >&2; exit 1; }}",
        f"if [ -e {lake} ]; then",
        f"  grep -qF {service} {lake} && ! grep -qF '\"organization\"' {lake} || {{",
        f"    printf 'error: %s names another service or organization\\n' {lake} >&2; exit 1; }}",
        "fi",
        no_link(PREFIX),
        f"chown 1000:1000 {PREFIX}",
        f"chmod 02751 {PREFIX}",
        *made(f"{PREFIX}/.tus-uploads", "00700"),
        no_link(lake),
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
        *made(helio, "02751"),
        *made(f"{helio}/.huron-objects", "00700"),
        no_link(f"{helio}/.huron"),
        f"[ -e {helio}/.huron ] || printf '%s\\n'"
        f" '{render_marker(helio_marker()).decode().rstrip()}' > {helio}/.huron",
        f"chmod 644 {helio}/.huron",
    ]
    assert "chown -R" not in script
    checked = subprocess.run(["sh", "-n"], input=script, text=True, check=False)
    assert checked.returncode == 0


def run_script(path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(path)], capture_output=True, text=True, check=False, cwd=cwd)


def owned_script(lake: Path, targets: list[OrganizationTarget], tmp_path: Path) -> Path:
    """The script for ``lake`` and ``targets``, owned by this process, written to a file."""
    script = tmp_path / "provision.sh"
    owner = Owner(os.getuid(), os.getgid())
    script.write_text(provision_script(str(lake), helio_marker(organization=None), owner, targets))
    return script


@NEEDS_SHELL
def test_the_script_runs_and_is_idempotent(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    root = lake / "root"
    root.mkdir(parents=True)
    owner = Owner(os.getuid(), os.getgid())
    script = owned_script(lake, [target(LakePath.of("root"), owner=owner)], tmp_path)
    for _ in range(2):
        done = run_script(script, tmp_path)
        assert done.returncode == 0, done.stderr
    directory = root / "helio"
    modes = {
        lake: ORGANIZATION_MODE,
        lake / UPLOAD_DIR: UPLOAD_DIR_MODE,
        directory: ORGANIZATION_MODE,
        directory / OBJECT_DIR: OBJECT_DIR_MODE,
        directory / MARKER_FILE: MARKER_MODE,
    }
    assert {path: stat.S_IMODE(os.lstat(path).st_mode) for path in modes} == modes
    storage = PosixStorage(lake)
    assert verify_marker(storage, LakePath.of("root", "helio"), INSTANCE, "helio") == helio_marker()
    assert verify_marker(storage, LakePath(), INSTANCE) == helio_marker(organization=None)
    (directory / MARKER_FILE).write_text(json.dumps({"instance_id": "other"}))
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1
    assert (
        refused.stderr
        == f"error: {directory / MARKER_FILE} names another service or organization\n"
    )
    shutil.rmtree(root)
    missing = run_script(script, tmp_path)
    assert missing.returncode == 1
    assert missing.stderr == f"error: the root {root} does not exist\n"
    (lake / MARKER_FILE).write_bytes(render_marker(helio_marker()))
    named = run_script(script, tmp_path)
    assert named.returncode == 1 and f"{lake}/.huron names another" in named.stderr
    shutil.rmtree(lake)
    gone = run_script(script, tmp_path)
    assert gone.returncode == 1 and f"the lake path {lake} does not exist" in gone.stderr


@NEEDS_SHELL
def test_the_script_refuses_a_link_at_a_directory_that_it_changes(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    (lake / "root").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    (lake / "root" / "helio").symlink_to(outside)
    owner = Owner(os.getuid(), os.getgid())
    script = owned_script(lake, [target(LakePath.of("root"), owner=owner)], tmp_path)
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1
    assert refused.stderr == f"error: {lake}/root/helio is a symbolic link\n"
    assert stat.S_IMODE(os.lstat(outside).st_mode) == 0o755
    assert not (outside / OBJECT_DIR).exists()


@NEEDS_SHELL
def test_the_script_never_expands_a_path(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    name = "$(touch pwned)`touch pwned`"
    root = lake / name
    owner = Owner(os.getuid(), os.getgid())
    script = owned_script(lake, [target(LakePath.of(name), owner=owner)], tmp_path)
    missing = run_script(script, tmp_path)
    assert missing.returncode == 1
    assert missing.stderr == f"error: the root {root} does not exist\n"
    root.mkdir()
    (root / "helio").mkdir()
    (root / "helio" / MARKER_FILE).write_text(json.dumps({"instance_id": "other"}))
    refused = run_script(script, tmp_path)
    assert refused.returncode == 1
    assert refused.stderr == f"error: {root}/helio/.huron names another service or organization\n"
    assert not (tmp_path / "pwned").exists()


def test_posix_storage_writes_files_with_the_mode_asked_for(tmp_path: Path) -> None:
    storage = PosixStorage(tmp_path)
    storage.write_bytes(LakePath.of("m"), b"x", MARKER_MODE)
    assert stat.S_IMODE(os.lstat(tmp_path / "m").st_mode) == MARKER_MODE


def expected(storage: MemoryStorage, own_marker: bool = True) -> list[Finding]:
    organization = ExpectedOrganization("helio", HELIO, INSTANCE, own_marker)
    return check_organization(storage, organization, START)


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
