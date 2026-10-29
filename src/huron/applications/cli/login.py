"""Logging in: the company OIDC device or loopback flow, then the Huron token exchange."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import CliError, ExitCode, NotLoggedIn
from huron.applications.cli.state import StateDir, Tokens
from huron.pkg.clock import Clock

__all__ = ["CompanyTokens", "Oidc", "Session", "pkce_pair"]

_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_RENEW_BEFORE = 300.0
_LOOPBACK_TIMEOUT = 120.0


@dataclass(frozen=True, slots=True)
class CompanyTokens:
    """What the company provider returned."""

    id_token: str
    refresh_token: str | None


class Oidc:
    """The company OIDC provider, from its discovery document."""

    def __init__(self, http: httpx.Client, issuer: str, client_id: str) -> None:
        if not issuer:
            raise CliError(
                "no identity provider is configured",
                ExitCode.USAGE,
                hint="run: huron config set issuer <url>",
            )
        self._http = http
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._discovery: dict[str, Any] | None = None

    def discovery(self) -> dict[str, Any]:
        """The provider's discovery document, fetched once."""
        if self._discovery is None:
            self._discovery = self._json("GET", f"{self._issuer}/.well-known/openid-configuration")
        return self._discovery

    def device_flow(
        self, announce: Callable[[str, str], None], sleep: Callable[[float], None]
    ) -> CompanyTokens:
        """Run the device authorization grant; ``announce(url, code)`` tells the user."""
        started = self._json(
            "POST",
            self.discovery()["device_authorization_endpoint"],
            data={"client_id": self._client_id, "scope": "openid profile"},
        )
        announce(
            str(started.get("verification_uri_complete") or started["verification_uri"]),
            str(started["user_code"]),
        )
        interval = float(started.get("interval", 5))
        while True:
            sleep(interval)
            answer = self._token(
                {"grant_type": _DEVICE_GRANT, "device_code": started["device_code"]}
            )
            error = answer.get("error")
            if error is None:
                return _company_tokens(answer)
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise CliError(f"login failed: {error}", ExitCode.NOT_LOGGED_IN)

    def loopback_flow(self, open_browser: Callable[[str], object]) -> CompanyTokens:
        """Run the authorization code flow with PKCE and a loopback redirect."""
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(16)
        receiver = _Receiver()
        redirect = receiver.start()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect,
                "scope": "openid profile",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        open_browser(f"{self.discovery()['authorization_endpoint']}?{query}")
        params = receiver.wait(_LOOPBACK_TIMEOUT)
        if params.get("state") != state or "code" not in params:
            raise CliError(
                "login failed: the browser did not return a code", ExitCode.NOT_LOGGED_IN
            )
        answer = self._token(
            {
                "grant_type": "authorization_code",
                "code": params["code"],
                "redirect_uri": redirect,
                "code_verifier": verifier,
            }
        )
        if "error" in answer:
            raise CliError(f"login failed: {answer['error']}", ExitCode.NOT_LOGGED_IN)
        return _company_tokens(answer)

    def refresh(self, refresh_token: str) -> CompanyTokens | None:
        """New tokens from a refresh token, or ``None`` when the provider refuses it."""
        answer = self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        if "error" in answer or "id_token" not in answer:
            return None
        return _company_tokens(answer)

    def _token(self, data: dict[str, str]) -> dict[str, Any]:
        return self._json(
            "POST",
            self.discovery()["token_endpoint"],
            data={"client_id": self._client_id, **data},
            accept_errors=True,
        )

    def _json(
        self, method: str, url: str, data: dict[str, str] | None = None, accept_errors: bool = False
    ) -> dict[str, Any]:
        try:
            response = self._http.request(method, url, data=data)
        except httpx.TransportError as error:
            raise CliError(f"the identity provider is unreachable: {error}") from error
        if response.status_code >= 400 and not (accept_errors and response.status_code == 400):
            raise CliError(f"the identity provider answered HTTP {response.status_code}")
        document: dict[str, Any] = response.json()
        return document


class Session:
    """The logged-in user's Huron token, renewed through the company refresh token."""

    def __init__(
        self, api: ApiClient, oidc: Callable[[], Oidc], state: StateDir, clock: Clock
    ) -> None:
        self._api = api
        self._oidc = oidc
        self._state = state
        self._clock = clock

    def login(self, tokens: CompanyTokens) -> Tokens:
        """Exchange company tokens for a Huron token and store it."""
        answer = self._api.post(
            "/api/v1/auth/exchange", json={"company_token": tokens.id_token}, auth=False
        )
        stored = Tokens(
            huron_token=answer["huron_token"],
            expires_at=datetime.fromisoformat(answer["expires_at"]).timestamp(),
            subject=answer["subject"],
            refresh_token=tokens.refresh_token,
        )
        self._state.write_tokens(stored)
        return stored

    def token(self) -> str:
        """A Huron token valid for at least five more minutes, renewing it when needed."""
        stored = self._state.read_tokens()
        if stored is None:
            raise NotLoggedIn()
        now = self._clock.now().timestamp()
        if stored.expires_at - now > _RENEW_BEFORE:
            return stored.huron_token
        if stored.refresh_token:
            renewed = self._oidc().refresh(stored.refresh_token)
            if renewed is not None:
                return self.login(renewed).huron_token
        if stored.expires_at > now:
            return stored.huron_token
        raise NotLoggedIn("your Huron session has expired")

    def logout(self) -> bool:
        """Forget the stored tokens."""
        return self._state.delete_tokens()


def pkce_pair() -> tuple[str, str]:
    """A PKCE ``(verifier, S256 challenge)`` pair."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _company_tokens(answer: dict[str, Any]) -> CompanyTokens:
    if "id_token" not in answer:
        raise CliError("login failed: the provider returned no ID token", ExitCode.NOT_LOGGED_IN)
    return CompanyTokens(str(answer["id_token"]), answer.get("refresh_token"))


class _Receiver:
    """A one-shot HTTP server on 127.0.0.1 that captures the redirect's query."""

    def __init__(self) -> None:
        self._params: dict[str, str] = {}
        self._done = threading.Event()
        self._server: HTTPServer | None = None

    def start(self) -> str:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = parse_qs(urlsplit(self.path).query)
                receiver._params = {k: v[0] for k, v in query.items()}
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Huron login complete. You can close this window.\n")
                receiver._done.set()

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.handle_request, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_port}/callback"

    def wait(self, timeout: float) -> dict[str, str]:
        finished = self._done.wait(timeout)
        if self._server is not None:
            self._server.server_close()
        if not finished:
            raise CliError("login timed out waiting for the browser", ExitCode.NOT_LOGGED_IN)
        return self._params
