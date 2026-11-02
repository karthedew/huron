"""``huron adm`` roles and schemas, ``create catalog --org`` and the ``set``/``unset`` verbs."""

import json
from pathlib import Path

import pytest

from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.unit.cli.conftest import PREFIX
from tests.unit.cli.test_collections import BASE_ANSWERS

REMINDER = "huron adm apply-acl heliophysics --recursive"


def groups(cli: Cli, role: str) -> list[str]:
    """The groups granted ``role`` on heliophysics itself, not inherited ones."""
    sources = json.loads(cli.ok("-o", "json", "get", "grants", "--catalog", "heliophysics").stdout)
    return [s["group"] for s in sources if s["role"] == role and s["scope"] == "catalog"]


def test_catalog_roles_default_to_the_current_catalog(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    refused = cli.run("adm", "grant", "reader", "guests")
    assert refused.exit_code == 2 and "huron catalog <name>" in refused.stderr
    cli.ok("catalog", "heliophysics")
    granted = cli.ok("adm", "grant", "reader", "guests")
    assert "reader: added guests, revoked -" in granted.stdout and REMINDER in granted.stdout
    assert "guests" in groups(cli, "reader")
    revoked = cli.ok("adm", "revoke", "reader", "guests")
    assert "revoked guests" in revoked.stdout and REMINDER in revoked.stdout
    assert "guests" not in groups(cli, "reader")


def test_the_catalog_option_wins_over_the_current_catalog(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.configure(current_catalog="elsewhere")
    cli.ok("adm", "grant", "contributor", "extra", "--catalog", "heliophysics")
    assert "extra" in groups(cli, "contributor")
    as_json = cli.ok(
        "-o", "json", "adm", "revoke", "contributor", "extra", "--catalog", "heliophysics"
    )
    assert as_json.stdout == ""


def test_org_admin_needs_an_organization(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("alice")
    cli.ok("catalog", "heliophysics")
    missing = cli.run("adm", "grant", "org_admin", "admins")
    assert missing.exit_code == 2 and "--org" in missing.stderr
    both = cli.run("adm", "grant", "org_admin", "admins", "--org", "helio", "--catalog", "x")
    assert both.exit_code == 2
    granted = cli.ok("adm", "grant", "org_admin", "admins", "--org", "helio")
    assert "org_admin: added admins" in granted.stdout and "apply-acl" not in granted.stdout
    cli.ok("adm", "revoke", "org_admin", "admins", "--org", "helio")
    grants = json.loads(cli.ok("-o", "json", "get", "grants", "--org", "helio").stdout)
    assert grants["org_admin"] == ["helio-org-admins"]


def test_unknown_roles_and_missing_groups_are_refused(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    assert cli.run("adm", "revoke", "owner", "x", "--catalog", "heliophysics").exit_code == 2
    assert cli.run("adm", "grant", "reader").exit_code == 2


def test_assign_schema_defaults_to_the_current_catalog(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("bob")
    base = json.loads(cli.ok("-o", "json", "get", "schemas").stdout)[0]["id"]
    assert cli.run("adm", "assign", "schema", base).exit_code == 2
    cli.ok("catalog", "heliophysics")
    assigned = cli.ok("adm", "assign", "schema", base)
    assert "heliophysics now uses huron-base v1" in assigned.stdout
    assert cli.run("adm", "assign", "schema", base, "--catalog", "missing").exit_code == 5


def test_create_catalog_requires_its_organization(seeded_cli: Cli, share: MemoryStorage) -> None:
    cli = seeded_cli
    cli.login_as("bob")
    missing = cli.run("create", "catalog", "spare")
    assert missing.exit_code == 2 and "--org" in missing.stderr
    assert cli.run("create", "catalog", "helio", "spare").exit_code == 2
    created = cli.ok("create", "catalog", "spare", "--org", "helio")
    assert "huron catalog spare" in created.stdout
    assert share.is_directory(PREFIX / "helio" / "spare")


def test_set_namespace_allows_and_forbids_collections(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("catalog", "heliophysics")
    cli.ok("create", "namespace", "archive")
    target = PREFIX / "helio" / "heliophysics" / "archive"
    allowed = cli.ok("set", "namespace", "archive", "--allow-collections")
    assert "heliophysics.archive allows collections" in allowed.stdout
    assert share.nodes[target].mode == 0o3770
    forbidden = cli.ok("set", "namespace", "archive", "--no-allow-collections")
    assert "does not allow collections" in forbidden.stdout
    assert share.nodes[target].mode == 0o2770
    assert cli.run("set", "namespace", "archive").exit_code == 2


@pytest.fixture
def collection(seeded_cli: Cli) -> Cli:
    """dave has created and checked out heliophysics.solar-wind.run7."""
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7")
    return cli


def test_set_and_unset_override(collection: Cli, tmp_path: Path) -> None:
    override = tmp_path / "override.json"
    override.write_text(json.dumps({"type": "object", "properties": {"run": {"type": "integer"}}}))
    assert "override set on" in collection.ok("set", "override", str(override)).stdout
    shown = json.loads(collection.ok("-o", "json", "get", "meta").stdout)
    assert shown["schema_override"]["properties"]["run"] == {"type": "integer"}
    assert "override cleared on" in collection.ok("unset", "override", "solar-wind.run7").stdout
    assert json.loads(collection.ok("-o", "json", "get", "meta").stdout)["schema_override"] is None
    assert collection.run("set", "override").exit_code == 2


def test_edit_meta_from_scratch_ignores_the_existing_draft(collection: Cli) -> None:
    copy = collection.config_current()
    collection.state.write_draft(copy, {"title": "Old", "description": "old", "kept": 1})
    collection.prompter.answers.extend(["New", "fresh", *([False] * 7)])
    edited = collection.ok("edit", "meta", "--from-scratch")
    assert "huron publish meta" in edited.stdout
    assert collection.state.read_draft(copy) == {"title": "New", "description": "fresh"}
    collection.state.write_draft(copy, {"title": "Old", "description": "old", "kept": 1})
    collection.prompter.answers.extend([None, None, *([False] * 7)])
    collection.ok("edit", "meta")
    assert collection.state.read_draft(copy) == {"title": "Old", "description": "old", "kept": 1}
