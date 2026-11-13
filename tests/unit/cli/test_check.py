"""``huron adm check`` and ``huron adm provision-catalogs`` over the in-memory share."""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from huron.core.storage import DIRECTORY_MODE, MARKER_FILE, OBJECT_DIR, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.support.clock import START
from tests.unit.cli.conftest import CATALOG, ORGANIZATION, PREFIX, make_collection
from tests.unit.cli.test_collections import BASE_ANSWERS

NAMESPACE = CATALOG.joinpath("solar-wind")
RUN7 = NAMESPACE.joinpath("run7")


@pytest.fixture
def built(seeded_cli: Cli) -> Cli:
    """The collection solar-wind.run7, created by dave, and its directory."""
    cli = seeded_cli
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7")
    make_collection(cli)
    return cli


def findings(cli: Cli, *argv: str) -> list[dict[str, str]]:
    """The findings of ``huron adm check`` with ``argv``, as JSON."""
    found: list[dict[str, str]] = json.loads(
        cli.run("-o", "json", "adm", "check", *argv).stdout or "[]"
    )
    return found


def test_a_consistent_share_checks_clean(built: Cli, tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    built.ok("add", str(source))
    built.ok("push")
    assert json.loads(built.run("-o", "json", "adm", "check").stdout) == []
    clean = built.run("adm", "check", "--catalog", "heliophysics", "--hash")
    assert clean.exit_code == 0, clean.stdout


def test_drift_is_reported(built: Cli, share: MemoryStorage) -> None:
    share.write_bytes(RUN7.joinpath("stray.txt"), b"x", 0o644)
    share.remove_file(RUN7.joinpath("metadata.json"))
    found = findings(built, "--catalog", "heliophysics")
    assert {"file_unrecorded", "sidecar_stale"} <= {f["code"] for f in found}


def test_check_stops_with_exit_code_2_when_the_share_is_not_mounted(built: Cli) -> None:
    built.configure(mount_prefix="/elsewhere")
    result = built.run("adm", "check")
    assert (result.exit_code, result.stdout) == (2, "")
    assert result.stderr.splitlines() == [
        "error: the root is not mounted on this machine [STORAGE_FAILED]",
        "hint: run this command on a machine that mounts the share, or set `mount_prefix`",
    ]


def test_check_stops_with_exit_code_2_when_the_marker_of_the_share_is_wrong(
    built: Cli, share: MemoryStorage
) -> None:
    share.write_bytes(
        LakePath.of(MARKER_FILE),
        json.dumps({"huron": 1, "api_url": "x", "instance_id": "other"}).encode(),
        0o644,
    )
    result = built.run("adm", "check")
    assert (result.exit_code, result.stdout) == (2, "")
    assert result.stderr.splitlines()[-1] == (
        "hint: run this command on a machine that mounts the share, or set `mount_prefix`"
    )


def test_check_stops_with_exit_code_2_when_the_marker_of_the_share_is_a_link(
    built: Cli, share: MemoryStorage
) -> None:
    share.remove_file(LakePath.of(MARKER_FILE))
    share.symlink(LakePath.of(MARKER_FILE), "/etc/hostname")
    result = built.run("adm", "check")
    assert (result.exit_code, result.stdout) == (2, "")
    assert result.stderr.splitlines()[0] == (
        "error: .huron is a symbolic link. The lake must not contain symbolic links. Remove it."
        " [SYMLINK_IN_LAKE]"
    )


def test_other_commands_keep_exit_code_8_when_the_share_is_not_mounted(built: Cli) -> None:
    built.configure(mount_prefix="/elsewhere")
    built.login_as("alice")
    result = built.run("adm", "provision-catalogs")
    assert result.exit_code == 8
    assert result.stderr.splitlines()[0] == (
        "error: the root is not mounted on this machine [STORAGE_FAILED]"
    )


def test_a_sidecar_with_integers_of_any_size_checks_fresh(
    built: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    metadata = tmp_path / "meta.json"
    metadata.write_text(
        '{"title": "Huge", "description": "d", "fill": -10000000000000000000000000000000}'
    )
    built.ok("create", "collection", "solar-wind.huge", "--metadata", str(metadata))
    make_collection(built, "huge")
    sidecar = share.read_bytes(CATALOG.joinpath("solar-wind", "huge", "metadata.json"))
    assert b'"fill":-10000000000000000000000000000000' in (sidecar or b"")
    found = findings(built, "--catalog", "heliophysics")
    assert all(f["code"] != "sidecar_stale" for f in found), found


def test_modes_owners_and_groups_are_compared_when_the_service_reports_its_user(
    built: Cli, share: MemoryStorage
) -> None:
    share.set_mode(NAMESPACE, 0o750)
    assert [(f["code"], f["path"], f["detail"]) for f in findings(built)] == [
        ("mode_drift", f"{PREFIX}/helio/heliophysics/solar-wind", "the mode is 750, not 2750")
    ]
    built.report_service_user(4242, share.gid + 1)
    owner = f"the owner is {share.uid}, not the service user 4242"
    group = f"the group is {share.gid}, not {share.gid + 1} (the service group)"
    catalog = f"{PREFIX}/helio/heliophysics"
    assert [(f["code"], f["path"], f["detail"]) for f in findings(built)] == [
        ("mode_drift", f"{PREFIX}/helio", owner),
        ("mode_drift", f"{PREFIX}/helio", group),
        ("mode_drift", catalog, owner),
        ("share_group_mismatch", catalog, group),
        ("mode_drift", f"{catalog}/solar-wind", "the mode is 750, not 2750"),
        ("mode_drift", f"{catalog}/solar-wind", owner),
        ("mode_drift", f"{catalog}/solar-wind/run7", owner),
        ("mode_drift", f"{catalog}/solar-wind/run7/metadata.json", owner),
    ]


def test_a_share_group_is_resolved_on_this_machine(built: Cli, share: MemoryStorage) -> None:
    built.login_as("bob")
    built.run("set", "catalog", "heliophysics", "--share-group", "readers")
    detail = {f["code"]: f["detail"] for f in findings(built)}["share_group_mismatch"]
    assert detail == "this machine does not know the share group readers"
    built.gids["readers"] = 4242
    detail = {f["code"]: f["detail"] for f in findings(built)}["share_group_mismatch"]
    assert detail == f"the group is {share.gid}, not 4242 (the share group readers)"
    built.gids["readers"] = share.gid
    assert findings(built) == []


def test_entries_that_the_check_cannot_read_or_links_are_reported(
    built: Cli, share: MemoryStorage
) -> None:
    share.make_directory(RUN7.joinpath("closed"), DIRECTORY_MODE)
    share.unreadable.add(RUN7.joinpath("closed"))
    share.symlink(RUN7.joinpath("link"), "/etc")
    result = built.run("-o", "json", "adm", "check")
    assert result.exit_code == 1
    assert [(f["code"], f["severity"], f["path"]) for f in json.loads(result.stdout)] == [
        ("symbolic_link", "error", f"{PREFIX}/helio/heliophysics/solar-wind/run7/link"),
        ("unreadable", "warning", f"{PREFIX}/helio/heliophysics/solar-wind/run7/closed"),
    ]


def test_a_pending_commit_is_reported_as_information(
    built: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    share.write_bytes(RUN7.joinpath("new.txt"), b"x", 0o644)
    forward: Callable[[httpx.Request], httpx.Response] = built.router.handle_request

    def pending(request: httpx.Request) -> httpx.Response:
        response = forward(request)
        if not request.url.path.endswith("/collections") or request.method != "GET":
            return response
        body = response.json()
        for item in body["items"]:
            item["pending_request"] = {"state": "blocked", "since": START.isoformat()}
        return httpx.Response(response.status_code, json=body)

    monkeypatch.setattr(built.router, "handle_request", pending)
    assert [(f["code"], f["severity"], f["detail"]) for f in findings(built)] == [
        (
            "pending_commit",
            "info",
            "a commit request is blocked."
            " Until the request ends, the directory can hold old and new files",
        )
    ]


def test_a_stale_probe_file_of_an_organization_is_reported_and_kept(
    built: Cli, share: MemoryStorage
) -> None:
    probe = ORGANIZATION.joinpath(OBJECT_DIR, ".huron-link-probe-0123456789abcdef0123456789abcdef")
    share.make_directory(ORGANIZATION.joinpath(OBJECT_DIR), 0o700)
    share.write_bytes(probe, b"", 0o644)
    share.nodes[probe].mtime_ns = int((START - timedelta(hours=2)).timestamp() * 1e9)
    assert [(f["code"], f["identifier"], f["path"]) for f in findings(built)] == [
        ("stale_link_probe", "helio", f"{PREFIX}/{probe}")
    ]
    assert share.stat(probe) is not None


def test_an_nfs_file_and_a_snapshot_directory_of_an_organization_are_reported_and_kept(
    built: Cli, share: MemoryStorage
) -> None:
    nfs = ORGANIZATION.joinpath(".nfs000000000123abcd00000001")
    snapshots = ORGANIZATION.joinpath(".snapshot")
    share.write_bytes(nfs, b"", 0o600)
    share.make_directory(snapshots, 0o777)
    result = built.run("-o", "json", "adm", "check")
    assert result.exit_code == 1, result.stderr
    assert [(f["code"], f["severity"], f["path"]) for f in json.loads(result.stdout)] == [
        ("nfs_file", "info", f"{PREFIX}/{nfs}"),
        ("snapshot_dir", "info", f"{PREFIX}/{snapshots}"),
    ]
    assert share.stat(nfs) is not None and share.stat(snapshots) is not None


@pytest.fixture
def storage_admin(seeded_cli: Cli, share: MemoryStorage) -> Cli:
    """alice, with the service user and group of the share reported by the service."""
    seeded_cli.login_as("alice")
    seeded_cli.report_service_user(share.uid, share.gid)
    return seeded_cli


def test_provision_catalogs_selects_nothing_on_a_share_without_drift(storage_admin: Cli) -> None:
    done = storage_admin.ok("adm", "provision-catalogs")
    assert done.stdout == "No catalog needs a new group or mode\n"
    assert json.loads(storage_admin.ok("-o", "json", "adm", "provision-catalogs").stdout) == []


def test_provision_catalogs_gives_the_selected_catalog_its_group_and_modes(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    share.set_mode(NAMESPACE, 0o750)
    calls = list(share.calls)
    planned = storage_admin.ok("adm", "provision-catalogs", "--dry-run").stdout
    assert planned == (
        f"heliophysics: would set group {share.gid} and mode 2750: {PREFIX}/helio/heliophysics\n"
    )
    assert share.calls == calls
    done = storage_admin.ok("adm", "provision-catalogs", "--catalog", "heliophysics").stdout
    assert done == (
        f"heliophysics: group {share.gid} and mode 2750:"
        f" 1 of 2 directories changed in {PREFIX}/helio/heliophysics\n"
    )
    assert share.nodes[NAMESPACE].mode == DIRECTORY_MODE
    again = storage_admin.ok("adm", "provision-catalogs")
    assert again.stdout == "No catalog needs a new group or mode\n"


def test_provision_catalogs_emits_a_script_and_changes_nothing(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    share.set_mode(NAMESPACE, 0o750)
    calls = list(share.calls)
    script = storage_admin.ok("adm", "provision-catalogs", "--emit-script", "--gid", "4242").stdout
    assert script.startswith("#!/bin/sh\n")
    assert script.splitlines()[-1] == (
        f"find {PREFIX}/helio/heliophysics -type d -exec chgrp 4242 {{}} + -exec chmod 2750 {{}} +"
    )
    assert share.calls == calls


def test_provision_catalogs_needs_the_service_group_for_a_catalog_without_a_share_group(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    seeded_cli.login_as("alice")
    refused = seeded_cli.run("adm", "provision-catalogs")
    assert refused.exit_code == 2
    assert refused.stderr.splitlines() == [
        "error: catalog heliophysics has no share group, and the CLI does not know the service"
        " group",
        "hint: use `--gid <gid>`",
    ]
    share.set_mode(NAMESPACE, 0o750)
    script = seeded_cli.ok("adm", "provision-catalogs", "--gid", str(share.gid), "--emit-script")
    assert script.stdout.splitlines()[-1] == (
        f"find {PREFIX}/helio/heliophysics -type d -exec chgrp {share.gid} {{}} +"
        " -exec chmod 2750 {} +"
    )


def test_provision_catalogs_reports_a_group_that_it_cannot_give(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    storage_admin.login_as("bob")
    storage_admin.run("set", "catalog", "heliophysics", "--share-group", "readers")
    storage_admin.login_as("alice")
    storage_admin.gids["readers"] = 4242
    share.groups["readers"] = 4242
    result = storage_admin.run("adm", "provision-catalogs")
    assert result.exit_code == 8
    assert result.stderr.splitlines() == [
        f"error: heliophysics: the CLI cannot give {PREFIX}/helio/heliophysics the group readers:"
        " Operation not permitted",
        "error: the CLI could not prepare 1 of 1 catalogs: heliophysics",
        "hint: when only `root` may change the groups,"
        " run `huron adm provision-catalogs --emit-script`",
    ]


def test_provision_catalogs_checks_the_marker_of_the_share(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    share.write_bytes(
        LakePath.of(MARKER_FILE),
        json.dumps({"huron": 1, "api_url": "x", "instance_id": "other"}).encode(),
        0o644,
    )
    refused = storage_admin.run("adm", "provision-catalogs")
    assert refused.exit_code == 8
    assert refused.stderr.splitlines() == [
        "error: the root belongs to another Huron service (x) [STORAGE_FAILED]",
        "hint: run this command on a machine that mounts the share, or set `mount_prefix`",
    ]


def test_provision_catalogs_leaves_a_catalog_that_it_cannot_read_to_the_check(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    share.unreadable.add(NAMESPACE)
    done = storage_admin.ok("adm", "provision-catalogs")
    assert done.stdout == "No catalog needs a new group or mode\n"
    script = storage_admin.ok("adm", "provision-catalogs", "--emit-script").stdout
    assert script.splitlines()[-2:] == ["set -eu", ""]


def test_provision_catalogs_fails_on_a_directory_that_it_cannot_read_in_a_selected_catalog(
    storage_admin: Cli, share: MemoryStorage
) -> None:
    share.set_mode(CATALOG, 0o750)
    share.unreadable.add(NAMESPACE)
    result = storage_admin.run("adm", "provision-catalogs")
    assert result.exit_code == 8
    assert result.stderr.splitlines() == [
        f"error: heliophysics: the CLI cannot read {PREFIX}/helio/heliophysics/solar-wind",
        "error: the CLI could not prepare 1 of 1 catalogs: heliophysics",
        "hint: when only `root` may change the groups,"
        " run `huron adm provision-catalogs --emit-script`",
    ]
    assert share.nodes[CATALOG].mode == 0o750
