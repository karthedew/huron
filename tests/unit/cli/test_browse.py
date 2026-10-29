"""Browsing and administration verbs that need no share."""

import json

from tests.support.cli import Cli


def test_organizations_and_grants(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("alice")
    listing = cli.ok("org", "list")
    assert "helio" in listing.stdout and "NAME" in listing.stdout
    described = json.loads(cli.ok("-o", "json", "org", "describe", "helio").stdout)
    assert described["catalog_count"] == 1
    cli.ok("org", "grant", "helio", "more-admins")
    grants = json.loads(cli.ok("-o", "json", "org", "grants", "helio").stdout)
    assert grants["ldap_groups"] == ["helio-org-admins", "more-admins"]
    revoked = cli.ok("org", "revoke", "helio", "more-admins")
    assert "removed more-admins" in revoked.stdout
    cli.login_as("erin")
    denied = cli.run("org", "grants", "helio")
    assert denied.exit_code == 4 and "FORBIDDEN" in denied.stderr


def test_catalogs_use_describe_and_roles(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    assert "heliophysics" in cli.ok("catalog", "list").stdout
    assert "heliophysics" in cli.ok("catalog", "list", "--org", "helio").stdout
    assert cli.run("catalog", "describe").exit_code == 2
    cli.ok("catalog", "use", "heliophysics")
    assert "huron-base v1" in cli.ok("catalog", "list").stdout
    assert "namespace_count" in cli.ok("catalog", "describe").stdout
    assert "helio-contributors" in cli.ok("catalog", "grants").stdout
    assert json.loads(cli.ok("-o", "json", "catalog", "grants").stdout)["reader"] == [
        "helio-readers"
    ]
    granted = cli.ok("catalog", "grant", "heliophysics", "reader", "guests")
    assert "acl apply" in granted.stdout
    cli.ok("catalog", "revoke", "heliophysics", "reader", "guests")
    assert cli.run("catalog", "use", "missing").exit_code == 5
    assert cli.run("catalog", "grant", "heliophysics", "owner", "x").exit_code == 2


def test_schemas(seeded_cli: Cli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cli = seeded_cli
    cli.login_as("bob")
    platform = json.loads(cli.ok("-o", "json", "schema", "list").stdout)
    base = platform[0]["id"]
    document = tmp_path / "helio.json"
    document.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"mission": {"type": "string"}},
                "required": ["mission"],
            }
        )
    )
    published = cli.ok("schema", "publish", "helio", "helio", str(document), "--extends", base)
    assert "published helio v1" in published.stdout
    listed = json.loads(cli.ok("-o", "json", "schema", "list", "helio").stdout)
    schema_id = listed[0]["id"]
    resolved = json.loads(cli.ok("-o", "json", "schema", "show", schema_id, "--resolved").stdout)
    assert "mission" in resolved["required"]
    assert cli.ok("schema", "show", schema_id).exit_code == 0
    assigned = cli.ok("schema", "assign", "heliophysics", schema_id)
    assert "heliophysics now uses helio v1: 0 active" in assigned.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    assert cli.run("schema", "publish", "helio", "x", str(bad)).exit_code == 2
    assert cli.run("schema", "publish", "helio", "x", str(tmp_path / "missing.json")).exit_code == 2
    cli.login_as("alice")
    platform_doc = tmp_path / "base.json"
    platform_doc.write_text(json.dumps({"type": "object"}))
    assert (
        "huron-base v2"
        in cli.ok("schema", "publish", "platform", "huron-base", str(platform_doc)).stdout
    )


def test_namespaces_collections_search_files_and_log(seeded_cli: Cli) -> None:
    cli = seeded_cli
    from huron.core.lake.collections.models import Update
    from tests.support.lake import CONTRIBUTOR, VALID_METADATA

    lake = cli.runtime.lake
    view = cli.loop.call(
        lake.collections.create(
            CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
        )
    )
    cli.loop.call(
        lake.collections.update(
            CONTRIBUTOR, view.collection.id, 1, Update(metadata_patch={"labels": {"site": "a"}})
        )
    )
    cli.loop.call(lake.collections.activate(CONTRIBUTOR, view.collection.id, 2))
    cli.login_as("erin")
    cli.ok("catalog", "use", "heliophysics")
    assert "heliophysics.solar-wind" in cli.ok("namespace", "list").stdout
    assert cli.ok("namespace", "list", "solar-wind").stdout.count("heliophysics") == 0
    assert "run7" in cli.ok("collection", "list", "solar-wind").stdout
    assert "Run 7" in cli.ok("collection", "describe", "solar-wind.run7").stdout
    assert "run7" in cli.ok("search", "-q", "solar", "-l", "site=a", "--state", "active").stdout
    assert "run7" in cli.ok("search", "heliophysics").stdout
    assert "PATH" in cli.ok("files", "solar-wind.run7").stdout
    assert "collection.activate" in cli.ok("log", "solar-wind.run7").stdout
    assert cli.run("collection", "describe").exit_code == 2
    assert cli.run("collection", "describe", "solar-wind.missing").exit_code == 5
    yaml_out = cli.ok("-o", "yaml", "whoami").stdout
    assert "subject: erin" in yaml_out
    assert (
        cli.ok(
            "--catalog",
            "heliophysics",
            "--api-url",
            "http://huron.test",
            "collection",
            "list",
            "solar-wind",
        ).exit_code
        == 0
    )
