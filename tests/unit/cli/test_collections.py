"""Creating, activating, checking out, pushing, pulling, editing and deleting collections."""

import json
from pathlib import Path

import pytest

from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.unit.cli.conftest import PREFIX, make_collection

COLLECTION = PREFIX / "helio" / "heliophysics" / "solar-wind" / "run7"
BASE_ANSWERS = ["Run 7", "Solar wind run seven", *([False] * 7)]


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    """The solar-wind directory exists and dave is logged in with heliophysics selected."""
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    return seeded_cli


def create(cli: Cli, name: str = "run7") -> None:
    """Create the collection through the CLI, then make its directory as the API will."""
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", f"solar-wind.{name}")
    make_collection(cli, name)


def files(tmp_path: Path, **contents: str) -> list[Path]:
    made = []
    for name, text in contents.items():
        path = tmp_path / name
        path.write_text(text)
        made.append(path)
    return made


def test_create_walks_through_metadata_and_activates(ready: Cli) -> None:
    ready.prompter.answers.extend(BASE_ANSWERS)
    created = ready.ok("create", "collection", "solar-wind.run7")
    assert created.stdout.startswith("collection heliophysics.solar-wind.run7 is active at ")
    described = json.loads(ready.ok("-o", "json", "describe", "collection").stdout)
    assert described["state"] == "active" and described["version"] == 3
    assert described["metadata"]["title"] == "Run 7"


def test_drafts_from_a_file_activate_later(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps({"title": "Run 8"}))
    ready.ok("create", "collection", "solar-wind.run8", "--metadata", str(metadata), "--draft")
    assert not share.exists(COLLECTION.with_name("run8"))
    refused = ready.run("activate", "collection")
    assert refused.exit_code == 7 and "METADATA_INVALID" in refused.stderr
    ready.prompter.answers.extend(["Run 8", "desc", *([False] * 7)])
    ready.ok("edit", "meta")
    ready.ok("validate", "meta")
    ready.ok("publish", "meta")
    ready.ok("activate", "collection")
    described = json.loads(ready.ok("-o", "json", "describe", "collection").stdout)
    assert described["identifier"] == "heliophysics.solar-wind.run8"
    assert described["state"] == "active"


def test_stage_push_status_and_pull(ready: Cli, share: MemoryStorage, tmp_path: Path) -> None:
    create(ready)
    a, b = files(tmp_path, **{"a.txt": "alpha", "b.txt": "bravo"})
    data = tmp_path / "data"
    (data / "deep").mkdir(parents=True)
    (data / "deep" / "c.txt").write_text("charlie")
    ready.ok("add", str(a), str(b))
    ready.ok("add", str(data), "--recursive")
    ready.ok("add", str(a), "--as", "renamed/a.txt")
    status = json.loads(ready.ok("-o", "json", "status").stdout)
    assert status["adds"] == ["a.txt", "b.txt", "deep/c.txt", "renamed/a.txt"]
    ready.ok("rm", "renamed/a.txt")
    pushed = ready.ok("push", "-m", "first data")
    assert "version 3 → 4, +3 −0 files" in pushed.stdout
    assert share.read_bytes(COLLECTION / "deep" / "c.txt") == b"charlie"
    assert "There is nothing to push" in ready.ok("push").stdout
    listing = ready.ok("get", "files").stdout
    assert "deep/c.txt" in listing
    ready.ok("rm", "b.txt")
    ready.ok("push")
    assert "b.txt" not in ready.ok("get", "files").stdout
    # The CLI unlinks nothing: the bytes of a removed file stay until the service removes them.
    assert share.read_bytes(COLLECTION / "b.txt") == b"bravo"
    share.write_bytes(COLLECTION / "stray.txt", b"x")
    status = json.loads(ready.ok("-o", "json", "status").stdout)
    assert status["unrecorded"] == ["b.txt", "stray.txt"] and status["behind"] is False
    assert "commit" in ready.ok("get", "log").stdout


def test_a_push_behind_the_service_is_refused_until_pull(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    create(ready)
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    copy = ready.state.read_copy(ready.config_current())
    ready.ok("unset", "override")
    assert copy is not None
    ready.state.write_copy(copy)
    behind = ready.run("push")
    assert behind.exit_code == 6 and "huron pull" in behind.stderr
    assert "behind" in ready.ok("status").stdout
    ready.ok("pull")
    assert "+1" in ready.ok("push").stdout


def test_metadata_overrides_and_publish(ready: Cli, tmp_path: Path) -> None:
    create(ready)
    override = tmp_path / "override.json"
    override.write_text(
        json.dumps(
            {"type": "object", "properties": {"run": {"type": "integer"}}, "required": ["run"]}
        )
    )
    refused = ready.run("set", "override", str(override))
    assert refused.exit_code == 7 and "METADATA_INVALID" in refused.stderr
    current = json.loads(ready.ok("-o", "json", "describe", "collection").stdout)["metadata"]
    ready.state.write_draft(ready.config_current(), {**current, "run": 7})
    ready.ok("set", "override", str(override))
    described = json.loads(ready.ok("-o", "json", "describe", "collection").stdout)
    assert described["schema_override"]["required"] == ["run"]
    shown = json.loads(ready.ok("-o", "json", "get", "meta").stdout)
    assert shown["metadata"]["run"] == 7 and shown["draft"] is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"type": "array"}))
    assert ready.run("set", "override", str(bad)).exit_code == 7
    assert ready.run("publish", "meta").exit_code == 2
    ready.state.write_draft(ready.config_current(), {"title": ""})
    invalid = ready.run("validate", "meta")
    assert invalid.exit_code == 7 and "/title" in invalid.stderr
    ready.prompter.answers.extend(["Fresh", "desc", "8", *([False] * 7)])
    ready.ok("edit", "meta", "--from-scratch")
    assert ready.state.read_draft(ready.config_current()) == {
        "title": "Fresh",
        "description": "desc",
        "run": 8,
    }
    ready.ok("publish", "meta")
    assert "Fresh" in ready.ok("describe", "collection").stdout


def test_checkout_keeps_each_copy_stage(ready: Cli, tmp_path: Path) -> None:
    create(ready)
    create(ready, "run9")
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    ready.ok("checkout", "solar-wind.run7")
    assert json.loads(ready.ok("-o", "json", "status").stdout)["adds"] == []
    ready.ok("checkout", "solar-wind.run9")
    assert json.loads(ready.ok("-o", "json", "status").stdout)["adds"] == ["a.txt"]


def test_staging_refusals(ready: Cli, tmp_path: Path) -> None:
    assert ready.run("add", str(tmp_path)).exit_code == 2
    create(ready)
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    (tmp_path / "link").symlink_to(a)
    (tmp_path / "metadata.json").write_text("{}")
    assert ready.run("add", str(tmp_path / "link")).exit_code == 2
    assert ready.run("add", str(tmp_path / "missing")).exit_code == 2
    assert ready.run("add", str(tmp_path)).exit_code == 2
    assert ready.run("add", str(tmp_path / "metadata.json")).exit_code == 2
    assert ready.run("add", str(a), "--as", "x.huron-part").exit_code == 2
    assert ready.run("add", str(a), str(a), "--as", "x").exit_code == 2
    assert ready.run("rm", "never.txt").exit_code == 2


def test_drafts_delete_without_touching_the_share(ready: Cli) -> None:
    ready.prompter.answers.extend(BASE_ANSWERS)
    ready.ok("create", "collection", "solar-wind.draft", "--draft")
    ready.ok("delete", "collection", "solar-wind.draft", "--yes")
    assert ready.run("describe", "collection", "solar-wind.draft").exit_code == 5


def test_others_cannot_delete_or_push(ready: Cli, share: MemoryStorage, tmp_path: Path) -> None:
    create(ready)
    (kept,) = files(tmp_path, **{"kept.txt": "kept"})
    ready.ok("add", str(kept))
    ready.ok("push")
    ready.login_as("frank")
    assert ready.run("delete", "collection", "solar-wind.run7", "--yes").exit_code == 4
    assert share.exists(COLLECTION / "kept.txt")
    ready.login_as("erin")
    ready.ok("checkout", "solar-wind.run7")
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    assert ready.run("push").exit_code == 4


def test_a_lost_commit_response_is_recovered(ready: Cli, tmp_path: Path) -> None:
    create(ready)
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    ready.router.fail_commits = "after"
    assert "3 → 4" in ready.ok("push").stdout
    assert json.loads(ready.ok("-o", "json", "status").stdout)["your_version"] == 4


def test_an_interrupted_push_resumes_without_copying_again(
    ready: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    create(ready)
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    ready.router.fail_commits = "before"
    failed = ready.run("push")
    assert failed.exit_code == 1 and "unreachable" in failed.stderr
    copies = [call for call in share.calls if call[0] == "copy"]
    ready.ok("push")
    assert [call for call in share.calls if call[0] == "copy"] == copies


def test_pull_drops_removals_of_files_no_longer_recorded(ready: Cli, tmp_path: Path) -> None:
    create(ready)
    (a,) = files(tmp_path, **{"a.txt": "alpha"})
    ready.ok("add", str(a))
    ready.ok("push")
    ready.ok("rm", "a.txt")
    copy = ready.state.read_copy(ready.config_current())
    ready.ok("push")
    assert copy is not None
    ready.state.write_copy(copy)
    ready.state.write_stage(
        copy.collection_id, ready.state.read_stage(copy.collection_id).__class__([], ["a.txt"])
    )
    pulled = ready.ok("pull")
    assert "no longer records" in pulled.stderr
