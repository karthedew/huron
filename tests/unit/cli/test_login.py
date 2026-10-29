"""Logging in by device code and by browser, renewing and logging out."""

import os
import threading
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx

from huron.applications.cli.state import Tokens
from tests.support.cli import Cli


def test_device_login_waits_for_approval(cli: Cli) -> None:
    cli.issuer.pending = 2
    result = cli.ok("login", "--device")
    assert "logged in as dave" in result.stdout
    assert "ABCD-EFGH" in result.stderr
    assert cli.slept == [1.0, 1.0, 1.0]
    tokens = cli.state.read_tokens()
    assert tokens is not None and tokens.refresh_token == "refresh-dave"
    assert os.stat(cli.state.root / "tokens.json").st_mode & 0o077 == 0
    me = cli.ok("whoami")
    assert "helio-contributors" in me.stdout


def test_device_login_slows_down_and_fails(cli: Cli) -> None:
    cli.issuer.device_error = "slow_down"
    calls = {"n": 0}
    original = cli.issuer._token

    def flip(form):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] > 1:
            cli.issuer.device_error = "access_denied"
        return original(form)

    cli.issuer._token = flip  # type: ignore[method-assign]
    result = cli.run("login", "--device")
    assert result.exit_code == 3 and "access_denied" in result.stderr
    assert cli.slept == [1.0, 6.0]


def test_browser_login_uses_a_loopback_redirect(cli: Cli) -> None:
    def browser(url: str) -> None:
        query = parse_qs(urlsplit(url).query)
        cli.issuer.codes["code-1"] = "erin"
        redirect = query["redirect_uri"][0]
        state = query["state"][0]
        threading.Thread(
            target=lambda: httpx.get(redirect, params={"code": "code-1", "state": state}),
            daemon=True,
        ).start()

    def services_with_browser():  # type: ignore[no-untyped-def]
        services, out, err = original()
        services.open_browser = browser
        return services, out, err

    original = cli.services
    cli.services = services_with_browser  # type: ignore[method-assign]
    result = cli.ok("login", "--browser")
    assert "logged in as erin" in result.stdout


def test_browser_login_refuses_a_wrong_state(cli: Cli) -> None:
    def browser(url: str) -> None:
        redirect = parse_qs(urlsplit(url).query)["redirect_uri"][0]
        threading.Thread(
            target=lambda: httpx.get(redirect, params={"code": "x", "state": "wrong"}), daemon=True
        ).start()

    original = cli.services

    def services_with_browser():  # type: ignore[no-untyped-def]
        services, out, err = original()
        services.open_browser = browser
        return services, out, err

    cli.services = services_with_browser  # type: ignore[method-assign]
    result = cli.run("login", "--browser")
    assert result.exit_code == 3


def test_display_selects_the_browser_flow(cli: Cli, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from huron.applications.cli.login import CompanyTokens, Oidc

    chosen: list[str] = []

    def fake_flow(self: Oidc, opener: object) -> CompanyTokens:
        chosen.append("browser")
        return CompanyTokens(cli.issuer.sign("dave", now=cli.issuer.now), None)

    monkeypatch.setattr(Oidc, "loopback_flow", fake_flow)
    cli.environ["DISPLAY"] = ":0"
    cli.ok("login")
    assert chosen == ["browser"]


def test_tokens_are_renewed_near_expiry(cli: Cli) -> None:
    cli.login_as("dave")
    first = cli.state.read_tokens()
    assert first is not None
    cli.clock.advance(timedelta(hours=8) - timedelta(minutes=1))
    cli.issuer.now = cli.clock.now().timestamp()
    cli.ok("whoami")
    renewed = cli.state.read_tokens()
    assert renewed is not None and renewed.expires_at > first.expires_at


def test_expired_sessions_without_renewal_must_log_in_again(cli: Cli) -> None:
    cli.login_as("dave")
    cli.issuer.refresh_ok = False
    cli.clock.advance(timedelta(hours=7, minutes=57))
    assert cli.run("whoami").exit_code == 0
    cli.clock.advance(timedelta(hours=1))
    result = cli.run("whoami")
    assert result.exit_code == 3 and "huron login" in result.stderr


def test_logout_and_missing_login(cli: Cli) -> None:
    assert cli.run("whoami").exit_code == 3
    cli.login_as("dave")
    assert "logged out" in cli.ok("logout").stdout
    assert "not logged in" in cli.ok("logout").stdout


def test_a_bad_token_is_reported_as_not_logged_in(cli: Cli) -> None:
    cli.state.write_tokens(Tokens("garbage", 4_000_000_000, "dave", None))
    result = cli.run("whoami")
    assert result.exit_code == 3 and "TOKEN_INVALID" in result.stderr


def test_login_needs_an_issuer(cli: Cli) -> None:
    cli.configure(issuer="")
    result = cli.run("login", "--device")
    assert result.exit_code == 2 and "config set issuer" in result.stderr


def test_unreachable_or_failing_providers(cli: Cli) -> None:
    cli.configure(issuer="https://other.test/realm")
    result = cli.run("login", "--device")
    assert result.exit_code == 1 and "HTTP" in result.stderr
