"""``huron check`` and ``huron acl apply`` over the in-memory share."""

import json

import pytest

from huron.core.storage.memory import MemoryStorage
from huron.pkg.fs.acl import Acl
from tests.support.cli import Cli
from tests.unit.cli.conftest import PREFIX
from tests.unit.cli.test_collections import BASE_ANSWERS

CATALOG = PREFIX / "helio" / "heliophysics"


@pytest.fixture
def built(seeded_cli: Cli, share: MemoryStorage) -> Cli:
    """A collection with one file, all created through the CLI by their owners."""
    cli = seeded_cli
    share.user = "carol"
    cli.login_as("carol")
    cli.ok("namespace", "create", "heliophysics.solar-wind", "--allow-collections")
    share.user = "dave"
    cli.login_as("dave")
    cli.ok("catalog", "use", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("collection", "create", "solar-wind.run7")
    return cli


def test_a_consistent_share_checks_clean(built: Cli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    built.ok("add", str(source))
    built.ok("push")
    drift = json.loads(built.run("-o", "json", "check").stdout)
    assert [f["code"] for f in drift] == ["acl_drift"]  # the seeded catalog directory
    built.ok("acl", "apply", "heliophysics")
    clean = built.run("check", "--catalog", "heliophysics", "--hash")
    assert clean.exit_code == 0, clean.stdout


def test_drift_is_reported(built: Cli, share: MemoryStorage) -> None:
    run7 = CATALOG / "solar-wind" / "run7"
    share.write_bytes(run7 / "stray.txt", b"x")
    share.remove_file(run7 / "metadata.json")
    findings = json.loads(built.run("-o", "json", "check", "--catalog", "heliophysics").stdout)
    assert {"file_unrecorded", "sidecar_stale"} <= {f["code"] for f in findings}


def test_acl_apply_repairs_what_the_caller_owns(built: Cli, share: MemoryStorage) -> None:
    run7 = CATALOG / "solar-wind" / "run7"
    share.nodes[run7].acl = Acl()
    result = built.run("acl", "apply", "solar-wind.run7")
    assert result.exit_code == 0 and "changed: heliophysics.solar-wind.run7" in result.stdout
    assert "unchanged" in built.ok("acl", "apply", "heliophysics.solar-wind.run7").stdout
    everything = built.run("acl", "apply", "heliophysics", "--recursive")
    assert everything.exit_code == 1 and "skipped (not yours" in everything.stderr
    assert built.run("acl", "apply", "heliophysics.nothing").exit_code == 8


def test_check_needs_the_share(built: Cli) -> None:
    built.configure(mount_prefix="/elsewhere")
    assert built.run("check").exit_code == 8


def test_acl_backend_none_skips_acl_findings(built: Cli) -> None:
    built.configure(acl_backend="none")
    findings = json.loads(built.run("-o", "json", "check").stdout or "[]")
    assert all(f["code"] != "acl_drift" for f in findings)
