"""``huron adm check`` over the in-memory share."""

import json
from pathlib import Path

import pytest

from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.unit.cli.conftest import CATALOG, make_collection
from tests.unit.cli.test_collections import BASE_ANSWERS


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


def test_a_consistent_share_checks_clean(built: Cli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    built.ok("add", str(source))
    built.ok("push")
    assert json.loads(built.run("-o", "json", "adm", "check").stdout) == []
    clean = built.run("adm", "check", "--catalog", "heliophysics", "--hash")
    assert clean.exit_code == 0, clean.stdout


def test_drift_is_reported(built: Cli, share: MemoryStorage) -> None:
    run7 = CATALOG / "solar-wind" / "run7"
    share.write_bytes(run7 / "stray.txt", b"x")
    share.remove_file(run7 / "metadata.json")
    findings = json.loads(
        built.run("-o", "json", "adm", "check", "--catalog", "heliophysics").stdout
    )
    assert {"file_unrecorded", "sidecar_stale"} <= {f["code"] for f in findings}


def test_check_needs_the_share(built: Cli) -> None:
    built.configure(mount_prefix="/elsewhere")
    assert built.run("adm", "check").exit_code == 8


def test_a_sidecar_with_integers_of_any_size_checks_fresh(
    built: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    metadata = tmp_path / "meta.json"
    metadata.write_text(
        '{"title": "Huge", "description": "d", "fill": -10000000000000000000000000000000}'
    )
    built.ok("create", "collection", "solar-wind.huge", "--metadata", str(metadata))
    make_collection(built, "huge")
    sidecar = share.read_bytes(CATALOG / "solar-wind" / "huge" / "metadata.json")
    assert b'"fill":-10000000000000000000000000000000' in (sidecar or b"")
    findings = json.loads(
        built.run("-o", "json", "adm", "check", "--catalog", "heliophysics").stdout or "[]"
    )
    assert all(f["code"] != "sidecar_stale" for f in findings), findings
