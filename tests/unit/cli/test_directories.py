"""Organization, catalog and namespace verbs that create directories on the share."""

import json
from pathlib import Path

from huron.core.storage import MARKER_FILE, DirectoryKind, Marker, render_marker
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.unit.cli.conftest import PREFIX


def named(share: MemoryStorage, path: Path) -> dict[str, str]:
    acl = share.nodes[path].acl
    return {e.qualifier: e.perms for e in acl.access if e.tag == "group" and e.qualifier}


def mounts(cli: Cli) -> list[dict[str, str]]:
    found: list[dict[str, str]] = json.loads(cli.run("-o", "json", "adm", "verify-mounts").stdout)
    return found


def test_verify_mounts_checks_the_share_root_marker(cli: Cli, share: MemoryStorage) -> None:
    cli.login_as("alice")
    empty = cli.ok("adm", "verify-mounts")
    assert empty.stdout.split()[:3] == ["ORG", "PATH", "STATE"]
    assert mounts(cli) == [{"organization": "-", "path": f"{PREFIX} (prefix)", "state": "ok"}]
    cli.ok("create", "org", "helio")
    assert mounts(cli) == [
        {"organization": "helio", "path": f"{PREFIX}/helio (prefix)", "state": "ok"}
    ]
    share.write_bytes(PREFIX / MARKER_FILE, render_marker(Marker(1, "http://other", "other-id")))
    refused = cli.run("adm", "verify-mounts")
    assert refused.exit_code == 1 and "wrong instance" in refused.stdout
    assert "scripts/init-root.sh" in refused.stdout and "provision-orgs" not in refused.stdout
    share.remove_file(PREFIX / MARKER_FILE)
    assert mounts(cli)[0]["state"] == "no marker"
    cli.configure(mount_prefix="/not/mounted")
    assert mounts(cli)[0]["state"] == "missing"
    assert cli.run("adm", "verify-mounts").exit_code == 1


def test_disk_operations_refuse_a_share_of_another_service(cli: Cli, share: MemoryStorage) -> None:
    cli.login_as("alice")
    cli.ok("create", "org", "helio")
    share.write_bytes(PREFIX / MARKER_FILE, render_marker(Marker(1, "http://other", "other-id")))
    cli.ok("adm", "grant", "org_admin", "helio-org-admins", "--org", "helio")
    cli.login_as("bob")
    refused = cli.run("create", "catalog", "heliophysics", "--org", "helio")
    assert refused.exit_code == 8 and "another Huron service" in refused.stderr
    assert "mounts the share" in refused.stderr
    cli.login_as("alice")
    assert json.loads(cli.ok("-o", "json", "get", "orgs").stdout)[0]["catalog_count"] == 0


def test_admins_build_the_tree_with_acls(cli: Cli, share: MemoryStorage) -> None:
    cli.login_as("alice")
    cli.ok("create", "org", "helio", "--display-name", "Heliophysics")
    org = PREFIX / "helio"
    assert share.nodes[org].mode == 0o2771
    assert named(share, org) == {"huron-platform-admins": "rwx"}
    cli.ok("adm", "grant", "org_admin", "helio-org-admins", "--org", "helio")
    cli.login_as("bob")
    result = cli.ok("create", "catalog", "heliophysics", "--org", "helio")
    assert "created: /projects/huron/helio/heliophysics" in result.stderr
    catalog = org / "heliophysics"
    assert named(share, catalog)["helio-org-admins"] == "rwx"
    cli.ok("adm", "grant", "catalog_admin", "helio-catalog-admins", "--catalog", "heliophysics")
    cli.login_as("carol")
    cli.ok("adm", "grant", "contributor", "helio-contributors", "--catalog", "heliophysics")
    cli.ok("adm", "grant", "reader", "helio-readers", "--catalog", "heliophysics")
    cli.ok("catalog", "heliophysics")
    cli.ok("create", "namespace", "solar-wind.l0.daily", "--parents", "--allow-collections")
    leaf = catalog / "solar-wind" / "l0" / "daily"
    assert share.nodes[leaf].mode == 0o3770
    assert named(share, leaf)["helio-contributors"] == "rwx"
    assert named(share, catalog / "solar-wind")["helio-contributors"] == "r-x"
    listing = json.loads(cli.ok("-o", "json", "get", "namespaces", "solar-wind.l0").stdout)
    assert listing[0]["collections_allowed"] is True
    cli.ok("set", "namespace", "solar-wind.l0.daily", "--no-allow-collections")
    assert share.nodes[leaf].mode == 0o2770


def test_creation_is_idempotent_and_repairs_missing_directories(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    first = cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    assert "created:" in first.stderr
    again = cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    assert "exists:" in again.stderr
    cli.login_as("bob")
    assert "exists:" in cli.ok("create", "catalog", "heliophysics", "--org", "helio").stderr


def test_missing_parents_are_refused_without_parents(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    result = cli.run("create", "namespace", "heliophysics.nope.child")
    assert result.exit_code == 5


def test_deletion_removes_empty_directories(seeded_cli: Cli, share: MemoryStorage) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("create", "namespace", "heliophysics.archive")
    target = PREFIX / "helio" / "heliophysics" / "archive"
    assert share.is_directory(target)
    cli.ok("delete", "namespace", "heliophysics.archive")
    assert not share.exists(target)
    cli.login_as("bob")
    cli.ok("create", "catalog", "spare", "--org", "helio")
    cli.ok("delete", "catalog", "spare")
    assert not share.exists(PREFIX / "helio" / "spare")
    cli.login_as("alice")
    cli.ok("create", "org", "geo")
    cli.ok("delete", "org", "geo")
    assert not share.exists(PREFIX / "geo")
    busy = cli.run("delete", "org", "helio")
    assert busy.exit_code == 6


def test_permission_failures_on_disk_exit_8(seeded_cli: Cli, share: MemoryStorage) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    share.denied.add(PREFIX / "helio" / "heliophysics")
    result = cli.run("create", "namespace", "heliophysics.blocked")
    assert result.exit_code == 8 and "permission denied" in result.stderr


def test_acl_backend_none_is_announced(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.configure(acl_backend="none")
    cli.login_as("carol")
    assert "modes only" in cli.ok("create", "namespace", "heliophysics.plain").stderr


def test_other_api_errors_pass_through(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("erin")
    assert cli.run("create", "catalog", "x", "--org", "helio").exit_code == 4
    assert cli.run("create", "org", "x").exit_code == 4
    assert cli.run("create", "namespace", "heliophysics.x").exit_code == 4


def test_directory_kinds_follow_the_namespace_flag() -> None:
    from huron.applications.cli.commands.common import kind_of

    assert kind_of({"collections_allowed": True}) is DirectoryKind.NAMESPACE_WITH_COLLECTIONS
    assert kind_of({"collections_allowed": False}) is DirectoryKind.NAMESPACE
