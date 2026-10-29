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


def test_verify_root_checks_the_marker(cli: Cli, share: MemoryStorage) -> None:
    result = cli.ok("platform", "verify-root")
    assert "Huron share of http://huron.test" in result.stdout
    share.write_bytes(PREFIX / MARKER_FILE, render_marker(Marker(1, "http://other", "other-id")))
    refused = cli.run("platform", "verify-root")
    assert refused.exit_code == 8 and "another Huron service" in refused.stderr
    assert "mounts the share" in refused.stderr
    cli.configure(mount_prefix="/not/mounted")
    assert cli.run("platform", "verify-root").exit_code == 8


def test_admins_build_the_tree_with_acls(cli: Cli, share: MemoryStorage) -> None:
    cli.login_as("alice")
    cli.ok("org", "create", "helio", "--display-name", "Heliophysics")
    org = PREFIX / "helio"
    assert share.nodes[org].mode == 0o2771
    assert named(share, org) == {"huron-platform-admins": "rwx"}
    cli.ok("org", "grant", "helio", "helio-org-admins")
    cli.login_as("bob")
    result = cli.ok("catalog", "create", "helio", "heliophysics")
    assert "created: /projects/huron/helio/heliophysics" in result.stderr
    catalog = org / "heliophysics"
    assert named(share, catalog)["helio-org-admins"] == "rwx"
    cli.ok("catalog", "grant", "heliophysics", "catalog_admin", "helio-catalog-admins")
    cli.login_as("carol")
    cli.ok("catalog", "grant", "heliophysics", "contributor", "helio-contributors")
    cli.ok("catalog", "grant", "heliophysics", "reader", "helio-readers")
    cli.ok("catalog", "use", "heliophysics")
    cli.ok("namespace", "create", "solar-wind.l0.daily", "--parents", "--allow-collections")
    leaf = catalog / "solar-wind" / "l0" / "daily"
    assert share.nodes[leaf].mode == 0o3770
    assert named(share, leaf)["helio-contributors"] == "rwx"
    assert named(share, catalog / "solar-wind")["helio-contributors"] == "r-x"
    listing = json.loads(cli.ok("-o", "json", "namespace", "list", "solar-wind.l0").stdout)
    assert listing[0]["collections_allowed"] is True
    cli.ok("namespace", "configure", "solar-wind.l0.daily", "--no-allow-collections")
    assert share.nodes[leaf].mode == 0o2770


def test_creation_is_idempotent_and_repairs_missing_directories(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    first = cli.ok("namespace", "create", "heliophysics.solar-wind", "--allow-collections")
    assert "created:" in first.stderr
    again = cli.ok("namespace", "create", "heliophysics.solar-wind", "--allow-collections")
    assert "exists:" in again.stderr
    cli.login_as("bob")
    assert "exists:" in cli.ok("catalog", "create", "helio", "heliophysics").stderr


def test_missing_parents_are_refused_without_parents(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    result = cli.run("namespace", "create", "heliophysics.nope.child")
    assert result.exit_code == 5


def test_deletion_removes_empty_directories(seeded_cli: Cli, share: MemoryStorage) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("namespace", "create", "heliophysics.archive")
    target = PREFIX / "helio" / "heliophysics" / "archive"
    assert share.is_directory(target)
    cli.ok("namespace", "delete", "heliophysics.archive")
    assert not share.exists(target)
    cli.login_as("bob")
    cli.ok("catalog", "create", "helio", "spare")
    cli.ok("catalog", "delete", "spare")
    assert not share.exists(PREFIX / "helio" / "spare")
    cli.login_as("alice")
    cli.ok("org", "create", "geo")
    cli.ok("org", "delete", "geo")
    assert not share.exists(PREFIX / "geo")
    busy = cli.run("org", "delete", "helio")
    assert busy.exit_code == 6


def test_permission_failures_on_disk_exit_8(seeded_cli: Cli, share: MemoryStorage) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    share.denied.add(PREFIX / "helio" / "heliophysics")
    result = cli.run("namespace", "create", "heliophysics.blocked")
    assert result.exit_code == 8 and "permission denied" in result.stderr


def test_acl_backend_none_is_announced(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.configure(acl_backend="none")
    cli.login_as("carol")
    assert "modes only" in cli.ok("namespace", "create", "heliophysics.plain").stderr


def test_other_api_errors_pass_through(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("erin")
    assert cli.run("catalog", "create", "helio", "x").exit_code == 4
    assert cli.run("org", "create", "x").exit_code == 4
    assert cli.run("namespace", "create", "heliophysics.x").exit_code == 4


def test_directory_kinds_follow_the_namespace_flag() -> None:
    from huron.applications.cli.commands.namespaces import kind_of

    assert kind_of({"collections_allowed": True}) is DirectoryKind.NAMESPACE_WITH_COLLECTIONS
    assert kind_of({"collections_allowed": False}) is DirectoryKind.NAMESPACE
