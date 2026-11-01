"""Browsing and administration verbs that need no share."""

import json

from tests.support.cli import Cli


def test_organizations_and_grants(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("alice")
    listing = cli.ok("get", "orgs")
    assert "helio" in listing.stdout and "NAME" in listing.stdout
    described = json.loads(cli.ok("-o", "json", "describe", "org", "helio").stdout)
    assert described["catalog_count"] == 1
    cli.ok("adm", "grant", "org_admin", "more-admins", "--org", "helio")
    grants = json.loads(cli.ok("-o", "json", "get", "grants", "--org", "helio").stdout)
    assert grants["org_admin"] == ["helio-org-admins", "more-admins"]
    revoked = cli.ok("adm", "revoke", "org_admin", "more-admins", "--org", "helio")
    assert "removed more-admins" in revoked.stdout
    cli.login_as("erin")
    denied = cli.run("get", "grants", "--org", "helio")
    assert denied.exit_code == 4 and "FORBIDDEN" in denied.stderr


def test_catalogs_use_describe_and_roles(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    assert "heliophysics" in cli.ok("get", "catalogs").stdout
    assert "heliophysics" in cli.ok("get", "catalogs", "--org", "helio").stdout
    assert cli.run("describe", "catalog").exit_code == 2
    cli.ok("catalog", "heliophysics")
    assert "huron-base v1" in cli.ok("get", "catalogs").stdout
    assert "namespace_count" in cli.ok("describe", "catalog").stdout
    assert "helio-contributors" in cli.ok("get", "grants").stdout
    sources = json.loads(cli.ok("-o", "json", "get", "grants").stdout)
    assert {"role": "reader", "group": "helio-readers", "scope": "catalog"} in sources
    granted = cli.ok("adm", "grant", "reader", "guests", "--catalog", "heliophysics")
    assert "huron adm apply-acl heliophysics --recursive" in granted.stdout
    cli.ok("adm", "revoke", "reader", "guests", "--catalog", "heliophysics")
    assert cli.run("catalog", "missing").exit_code == 5
    assert cli.run("adm", "grant", "owner", "x", "--catalog", "heliophysics").exit_code == 2


def test_schemas(seeded_cli: Cli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cli = seeded_cli
    cli.login_as("bob")
    platform = json.loads(cli.ok("-o", "json", "get", "schemas").stdout)
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
    published = cli.ok(
        "adm", "publish", "schema", "helio", "helio", str(document), "--extends", base
    )
    assert "published helio v1" in published.stdout
    listed = json.loads(cli.ok("-o", "json", "get", "schemas", "helio").stdout)
    schema_id = listed[0]["id"]
    resolved = json.loads(
        cli.ok("-o", "json", "describe", "schema", schema_id, "--resolved").stdout
    )
    assert "mission" in resolved["required"]
    assert cli.ok("describe", "schema", schema_id).exit_code == 0
    assigned = cli.ok("adm", "assign", "schema", schema_id, "--catalog", "heliophysics")
    assert "heliophysics now uses helio v1: 0 active" in assigned.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    assert cli.run("adm", "publish", "schema", "helio", "x", str(bad)).exit_code == 2
    assert (
        cli.run("adm", "publish", "schema", "helio", "x", str(tmp_path / "missing.json")).exit_code
        == 2
    )
    cli.login_as("alice")
    platform_doc = tmp_path / "base.json"
    platform_doc.write_text(json.dumps({"type": "object"}))
    assert (
        "huron-base v2"
        in cli.ok("adm", "publish", "schema", "platform", "huron-base", str(platform_doc)).stdout
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
    cli.ok("catalog", "heliophysics")
    assert "heliophysics.solar-wind" in cli.ok("get", "namespaces").stdout
    assert cli.ok("get", "namespaces", "solar-wind").stdout.count("heliophysics") == 0
    assert "run7" in cli.ok("get", "collections", "solar-wind").stdout
    assert "Run 7" in cli.ok("describe", "collection", "solar-wind.run7").stdout
    assert "run7" in cli.ok("search", "-q", "solar", "-l", "site=a", "--state", "active").stdout
    assert "run7" in cli.ok("--catalog", "heliophysics", "search").stdout
    assert "PATH" in cli.ok("get", "files", "solar-wind.run7").stdout
    assert "collection.activate" in cli.ok("get", "log", "solar-wind.run7").stdout
    assert cli.run("describe", "collection").exit_code == 2
    assert cli.run("describe", "collection", "solar-wind.missing").exit_code == 5
    yaml_out = cli.ok("-o", "yaml", "whoami").stdout
    assert "subject: erin" in yaml_out
    assert (
        cli.ok(
            "--catalog",
            "heliophysics",
            "--api-url",
            "http://huron.test",
            "get",
            "collections",
            "solar-wind",
        ).exit_code
        == 0
    )
