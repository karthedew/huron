"""The CLI's root app, configuration, state, output and API client."""

import json
import os
from pathlib import Path

import httpx
import pytest
from rich.console import Console

from huron.applications.cli.client import ApiClient
from huron.applications.cli.config import Config, config_path
from huron.applications.cli.errors import ApiError, CliError, ExitCode, exit_code_for
from huron.applications.cli.identifiers import qualify, resolve_collection, resolve_namespace
from huron.applications.cli.output import Column, OutputFormat, render, render_one
from huron.applications.cli.state import Stage, StagedAdd, StateDir, Tokens, WorkingCopy, state_root
from tests.support.cli import Cli


def test_help_and_usage_errors(cli: Cli) -> None:
    assert cli.run("--help").exit_code == 0
    assert cli.run("no-such-command").exit_code == 2
    assert cli.run("org", "describe").exit_code == 2


def test_unexpected_failures_are_reported_or_raised_in_debug(cli: Cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(Config, "as_dict", boom)
    result = cli.run("config", "show")
    assert result.exit_code == 1 and "HURON_DEBUG" in result.stderr
    cli.environ["HURON_DEBUG"] = "1"
    with pytest.raises(RuntimeError):
        cli.run("config", "show")


def test_interrupts_and_aborts_exit_130(cli: Cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import typer

    for error in (KeyboardInterrupt(), typer.Abort()):

        def raiser(*args: object, error: BaseException = error) -> None:
            raise error

        monkeypatch.setattr(Config, "as_dict", raiser)
        assert cli.run("config", "show").exit_code == 130


def test_config_show_and_set(cli: Cli) -> None:
    shown = cli.ok("-o", "json", "config", "show")
    assert json.loads(shown.stdout)["api_url"] == "http://huron.test"
    cli.ok("config", "set", "mount_prefix", "/mnt/share")
    assert "/mnt/share" in cli.ok("config", "show").stdout
    refused = cli.run("config", "set", "nope", "x")
    assert refused.exit_code == 2 and "keys:" in refused.stderr
    assert cli.run("config", "set", "acl_backend", "magic").exit_code == 2
    assert os.stat(cli.config_path).st_mode & 0o077 == 0


def test_config_files_and_environment(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("api_url: http://a\nunknown: 1\n")
    config = Config.load(path, {"HURON_MOUNT_PREFIX": "/m"})
    assert (config.api_url, config.mount_prefix) == ("http://a", "/m")
    path.write_text("- not a mapping\n")
    with pytest.raises(CliError):
        Config.load(path, {})
    assert Config.load(tmp_path / "missing.yaml", {}).api_url.startswith("http")
    assert config_path({"XDG_CONFIG_HOME": "/x"}) == Path("/x/huron/config.yaml")
    assert config_path({"HOME": "/h"}) == Path("/h/.config/huron/config.yaml")
    assert state_root({"XDG_STATE_HOME": "/s"}) == Path("/s/huron")
    assert state_root({"HOME": "/h"}) == Path("/h/.local/state/huron")


def test_state_round_trips_and_guards_tokens(tmp_path: Path) -> None:
    state = StateDir(tmp_path / "state")
    assert state.read_tokens() is None and state.delete_tokens() is False
    state.write_tokens(Tokens("t", 1.0, "dave", None))
    assert state.read_tokens() == Tokens("t", 1.0, "dave", None)
    os.chmod(state.root / "tokens.json", 0o644)
    with pytest.raises(CliError) as raised:
        state.read_tokens()
    assert raised.value.exit_code == ExitCode.NOT_LOGGED_IN
    assert state.delete_tokens() is True
    copy = WorkingCopy("id", "c.n.x", 2, "o/c/n/x")
    state.write_copy(copy)
    assert state.read_copy("id") == copy and state.read_copy("other") is None
    stage = Stage([StagedAdd("a", "/tmp/a", 1)], ["b"])
    state.write_stage("id", stage)
    assert state.read_stage("id") == stage and Stage().empty and not stage.empty
    state.write_draft("id", {"title": "x"})
    assert state.read_draft("id") == {"title": "x"}
    state.delete_draft("id")
    assert state.read_draft("id") is None
    with state.locked("id"), pytest.raises(CliError) as busy, state.locked("id"):
        pass  # pragma: no cover
    assert busy.value.exit_code == ExitCode.CONFLICT


def test_output_formats() -> None:
    import io

    buffer = io.StringIO()
    console = Console(file=buffer, width=120, color_system=None)
    rows = [{"name": "a", "n": None, "d": {"k": 1}}]
    columns = [
        Column("NAME", lambda r: r["name"]),
        Column("N", lambda r: r["n"]),
        Column("D", lambda r: r["d"]),
    ]
    render(console, rows, columns, OutputFormat.TABLE)
    render(console, rows, columns, OutputFormat.JSON)
    render(console, rows, columns, OutputFormat.YAML)
    render_one(console, {"key": [1]}, OutputFormat.TABLE)
    render_one(console, {"key": 1}, OutputFormat.JSON)
    render_one(console, {"key": 1}, OutputFormat.YAML)
    text = buffer.getvalue()
    assert '{"k": 1}' in text and '"name": "a"' in text and "- name: a" in text
    assert "key  [1]" in text and "key: 1" in text


def test_identifiers_resolve_against_the_current_catalog() -> None:
    assert qualify("ns.x", "helio") == "helio.ns.x"
    assert qualify("helio.ns.x", "helio") == "helio.ns.x"
    assert qualify("helio", "helio") == "helio"
    assert qualify("a.b", None) == "a.b"
    assert str(resolve_collection("ns.x", "helio")) == "helio.ns.x"
    assert resolve_namespace("ns", "helio").namespace == "ns"
    with pytest.raises(CliError):
        resolve_collection("ns", "helio")
    with pytest.raises(CliError):
        resolve_namespace("Bad", None)


def test_api_errors_map_to_exit_codes() -> None:
    cases = {
        "UNAUTHENTICATED": ExitCode.NOT_LOGGED_IN,
        "FORBIDDEN": ExitCode.FORBIDDEN,
        "NOT_FOUND": ExitCode.NOT_FOUND,
        "NAME_TAKEN": ExitCode.CONFLICT,
        "CATALOG_NOT_EMPTY": ExitCode.CONFLICT,
        "BASE_VERSION_CONFLICT": ExitCode.CONFLICT,
        "METADATA_INVALID": ExitCode.VALIDATION,
        "SCHEMA_SCOPE": ExitCode.VALIDATION,
        "FILE_NOT_RECORDED": ExitCode.VALIDATION,
        "STORAGE_FAILED": ExitCode.STORAGE,
        "ACL_FAILED": ExitCode.STORAGE,
        "INTERNAL": ExitCode.FAILED,
    }
    for code, expected in cases.items():
        assert exit_code_for(code, 400) == expected
    error = ApiError.from_problem(409, {"code": "BASE_VERSION_CONFLICT", "detail": "pull"})
    assert error.hint == "run: huron pull"
    assert ApiError.from_problem(500, {"code": "X"}).message == "HTTP 500"


def test_client_retries_reads_maps_errors_and_pages() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/flaky" and calls.count("/flaky") < 3:
            raise httpx.ConnectError("down", request=request)
        if request.url.path == "/down":
            raise httpx.ConnectError("down", request=request)
        if request.url.path == "/html":
            return httpx.Response(502, text="<html>")
        if request.url.path == "/pages":
            cursor = request.url.params.get("cursor")
            return httpx.Response(
                200,
                json={"items": [cursor or "first"], "next_cursor": None if cursor else "second"},
            )
        if request.url.path == "/empty":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True})

    slept: list[float] = []
    client = ApiClient(
        httpx.Client(transport=httpx.MockTransport(handler)), "http://x/", None, slept.append
    )
    assert client.get("/flaky") == {"ok": True} and len(slept) == 2
    with pytest.raises(CliError) as down:
        client.get("/down")
    assert "unreachable" in down.value.message
    with pytest.raises(CliError, match="HTTP 502"):
        client.get("/html")
    with pytest.raises(CliError):
        client.post("/down")
    assert list(client.pages("/pages")) == ["first", "second"]
    assert client.post("/empty") is None and client.patch("/x") == {"ok": True}
    assert client.put("/x") == {"ok": True}
    client.delete("/x")
    assert client.get("http://x/absolute") == {"ok": True}


def test_domain_errors_are_reported_with_their_code(cli: Cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from huron.schema.naming import NamingError

    def refuse(*args: object) -> None:
        raise NamingError("segment_chars", "Bad")

    monkeypatch.setattr(Config, "as_dict", refuse)
    result = cli.run("config", "show")
    assert result.exit_code == 7 and "[NAME_INVALID]" in result.stderr
