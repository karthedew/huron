"""An in-process company issuer with real signatures and controllable failures."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_hex, token_urlsafe
from functools import cache
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from starlette.requests import Request

    from huron.core.foundation.clock import Clock
    from tests.fakes.ldap_groups import Identities

Endpoint = Literal["discovery", "jwks", "authorize", "token", "device", "revoke"]
IdpFailure = int | Literal["timeout", "unreachable", "malformed", "issuer_mismatch"]
DeviceStep = Literal["authorization_pending", "slow_down", "access_denied", "expired_token"]
SigningKey = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey


@dataclass(frozen=True, slots=True)
class Approve:
    """Approve the next polled device grant as a fixture user.

    Attributes:
        username: Fixture user validated when the control is queued.
    """

    username: str


@dataclass(frozen=True, slots=True)
class _Code:
    username: str
    redirect: str
    challenge: str
    nonce: str | None
    scope: str
    expires: datetime


@dataclass(slots=True)
class _Device:
    challenge: str
    scope: str
    expires: datetime
    interval: int
    last_poll: datetime | None = None
    username: str | None = None
    denied: bool = False
    consumed: bool = False


@dataclass(slots=True)
class _RefreshFamily:
    username: str
    scope: str
    current: str
    revoked: bool = False


def _pkce_matches(verifier: str, challenge: str) -> bool:
    digest = urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return bool(verifier) and digest == challenge


def _loopback_redirect(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            value.startswith("http://127.0.0.1:")
            and not any(character.isspace() or ord(character) < 32 for character in value)
            and url.scheme == "http"
            and url.hostname == "127.0.0.1"
            and url.port is not None
            and url.port > 0
            and bool(url.path)
            and url.username is None
            and url.password is None
            and not url.fragment
        )
    except ValueError:
        return False


def _error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


async def _form(request: Request) -> dict[str, str]:
    return {
        key.decode(): values[0].decode() for key, values in parse_qs(await request.body()).items()
    }


@cache
def _default_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_jwk(kid: str, key: SigningKey) -> dict[str, object]:
    if isinstance(key, rsa.RSAPrivateKey):
        members = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
        algorithm = "RS256"
    else:
        members = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
        algorithm = "ES256"
    return {**members, "kid": kid, "alg": algorithm, "use": "sig"}


class FakeCompanyIdp:
    """Publish company identity tokens through a deterministic HTTP boundary."""

    def __init__(
        self,
        identities: Identities,
        clock: Clock,
        *,
        issuer: str = "https://idp.test/realms/company",
        client_id: str = "huron-cli",
        token_ttl: timedelta = timedelta(seconds=300),
        device_ttl: timedelta = timedelta(seconds=600),
        interval: int = 5,
        revocation: bool = True,
    ) -> None:
        """Build an isolated issuer using the shared clock and immutable people.

        Args:
            identities: People whose claims can be minted.
            clock: Source of all token times.
            issuer: Issuer URL, including the realm path.
            client_id: Public client and token audience.
            token_ttl: ID-token lifetime.
            device_ttl: Device authorization lifetime.
            interval: Device polling interval in seconds.
            revocation: Whether discovery advertises revocation.
        """
        self._lock = Lock()
        self._identities = identities
        self._clock = clock
        self._issuer = issuer
        self._client_id = client_id
        self._token_ttl = token_ttl
        self._device_ttl = device_ttl
        self._interval = interval
        self._revocation = revocation
        self._keys: dict[str, SigningKey] = {"fake-rs256-1": _default_key()}
        self._current_kid = "fake-rs256-1"
        self._rotation = 0
        self._failures: dict[Endpoint, IdpFailure] = {}
        self._hits: dict[Endpoint, int] = dict.fromkeys(
            ("discovery", "jwks", "authorize", "token", "device", "revoke"), 0
        )
        self._login_as = "karl"
        identities.user(self._login_as)
        self._authorize_error: str | None = None
        self._codes: dict[str, _Code] = {}
        self._devices: dict[str, _Device] = {}
        self._user_codes: dict[str, _Device] = {}
        self._device_steps: deque[DeviceStep | Approve] = deque()
        self._refresh: dict[str, _RefreshFamily] = {}
        self._revoked: list[str] = []
        path = urlsplit(issuer).path
        self._app = Starlette(
            routes=[
                Route(path + "/.well-known/openid-configuration", self._discovery),
                Route(path + "/protocol/openid-connect/certs", self._jwks),
                Route(path + "/protocol/openid-connect/auth", self._authorize),
                Route(
                    path + "/protocol/openid-connect/auth/device", self._device, methods=["POST"]
                ),
                Route(path + "/protocol/openid-connect/token", self._token, methods=["POST"]),
                Route(path + "/protocol/openid-connect/revoke", self._revoke, methods=["POST"]),
            ]
        )

    @property
    def issuer(self) -> str:
        """Return the fixed issuer URL."""
        return self._issuer

    @property
    def client_id(self) -> str:
        """Return the fixed public client identifier."""
        return self._client_id

    @property
    def app(self) -> Starlette:
        """Return the one app shared by asynchronous and threaded clients."""
        return self._app

    @property
    def hits(self) -> Mapping[Endpoint, int]:
        """Return an immutable snapshot of endpoint request counts."""
        with self._lock:
            return MappingProxyType(dict(self._hits))

    @property
    def login_as(self) -> str:
        """Return the user auto-approved by authorization requests."""
        with self._lock:
            return self._login_as

    @login_as.setter
    def login_as(self, username: str) -> None:
        """Select the fixture user for subsequent authorization requests.

        Args:
            username: Existing fixture username.

        Raises:
            KeyError: The username is unknown.
        """
        with self._lock:
            self._identities.user(username)
            self._login_as = username

    @property
    def revoked(self) -> tuple[str, ...]:
        """Return tokens submitted for revocation, in request order."""
        with self._lock:
            return tuple(self._revoked)

    def deny_authorize(self, error: str | None) -> None:
        """Set an authorization error, or clear it with None.

        Args:
            error: OAuth error to redirect to the validated callback.
        """
        with self._lock:
            self._authorize_error = error

    def approve(self, user_code: str, username: str) -> None:
        """Approve a device code as an existing fixture user.

        Args:
            user_code: User-facing code from a device authorization.
            username: Fixture user approving the grant.

        Raises:
            KeyError: The code or username is unknown.
        """
        with self._lock:
            self._identities.user(username)
            self._user_codes[user_code].username = username

    def script_device(self, *steps: DeviceStep | Approve) -> None:
        """Queue responses consumed in order by device polls.

        Args:
            *steps: OAuth errors or approval controls to append.

        Raises:
            KeyError: An approval names an unknown user.
        """
        with self._lock:
            for step in steps:
                if isinstance(step, Approve):
                    self._identities.user(step.username)
            self._device_steps.extend(steps)

    def inject(self, endpoint: Endpoint, failure: IdpFailure | None) -> None:
        """Set a persistent endpoint failure, or clear it with None.

        Args:
            endpoint: Endpoint whose subsequent requests are affected.
            failure: Status, transport fault or malformed document to return.

        Raises:
            ValueError: Issuer mismatch was requested outside discovery.
        """
        if failure == "issuer_mismatch" and endpoint != "discovery":
            raise ValueError("issuer_mismatch applies only to discovery")
        with self._lock:
            if failure is None:
                self._failures.pop(endpoint, None)
            else:
                self._failures[endpoint] = failure

    def rotate_key(self, *, retire_previous: bool = False) -> str:
        """Publish and activate a fresh P-256 signing key.

        Args:
            retire_previous: Remove the previously active key from publication.

        Returns:
            The new signing key's identifier.
        """
        with self._lock:
            self._rotation += 1
            kid = f"fake-es256-{self._rotation}"
            if retire_previous:
                del self._keys[self._current_kid]
            self._keys[kid] = ec.generate_private_key(ec.SECP256R1())
            self._current_kid = kid
            return kid

    def id_token(
        self,
        username: str,
        *,
        claims: Mapping[str, object] | None = None,
        drop: Iterable[str] = (),
        kid: str | None = None,
        forged: bool = False,
    ) -> str:
        """Mint a signed ID token, optionally corrupting claims or its signature.

        Args:
            username: Fixture username whose identity to assert.
            claims: Claim additions and overrides.
            drop: Claim names to omit after applying overrides.
            kid: Published key to use, or None for the active key.
            forged: Sign with an unpublished key of the selected algorithm.

        Returns:
            A compact signed JWT.

        Raises:
            KeyError: The username or signing key is unknown.
        """
        with self._lock:
            return self._sign_token(username, claims=claims, drop=drop, kid=kid, forged=forged)

    def _sign_token(
        self,
        username: str,
        *,
        claims: Mapping[str, object] | None = None,
        drop: Iterable[str] = (),
        kid: str | None = None,
        forged: bool = False,
    ) -> str:
        user = self._identities.user(username)
        now = self._clock.now()
        body: dict[str, object] = {
            "iss": self._issuer,
            "sub": user.id,
            "aud": self._client_id,
            "azp": self._client_id,
            "iat": int(now.timestamp()),
            "auth_time": int(now.timestamp()),
            "exp": int((now + self._token_ttl).timestamp()),
            "preferred_username": user.username,
            "name": f"{user.given_name} {user.family_name}",
            "given_name": user.given_name,
            "family_name": user.family_name,
            "email": user.email,
            "email_verified": True,
            "organization": self._identities.organization,
            "sid": f"session-{user.id}",
            "typ": "ID",
        }
        body.update(claims or {})
        for name in drop:
            body.pop(name, None)
        selected = kid if kid is not None else self._current_kid
        key = self._keys[selected]
        algorithm = "RS256" if isinstance(key, rsa.RSAPrivateKey) else "ES256"
        if forged:
            key = (
                rsa.generate_private_key(public_exponent=65537, key_size=2048)
                if algorithm == "RS256"
                else ec.generate_private_key(ec.SECP256R1())
            )
        return jwt.encode(body, key, algorithm=algorithm, headers={"kid": selected})

    def _failure(self, endpoint: Endpoint) -> Response | None:
        self._hits[endpoint] += 1
        failure = self._failures.get(endpoint)
        if isinstance(failure, int):
            return JSONResponse({"error": "injected"}, status_code=failure)
        if failure == "timeout":
            raise httpx.ReadTimeout("injected")
        if failure == "unreachable":
            raise httpx.ConnectError("injected")
        if failure == "malformed":
            return PlainTextResponse("not json")
        return None

    async def _discovery(self, request: Request) -> Response:
        with self._lock:
            failure = self._failure("discovery")
            if failure is not None:
                return failure
            base = self._issuer + "/protocol/openid-connect"
            document: dict[str, object] = {
                "issuer": self._issuer,
                "authorization_endpoint": base + "/auth",
                "token_endpoint": base + "/token",
                "device_authorization_endpoint": base + "/auth/device",
                "jwks_uri": base + "/certs",
                "response_types_supported": ["code"],
                "grant_types_supported": [
                    "authorization_code",
                    "refresh_token",
                    "urn:ietf:params:oauth:grant-type:device_code",
                ],
                "code_challenge_methods_supported": ["S256"],
                "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                "subject_types_supported": ["public"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
            if self._revocation:
                document["revocation_endpoint"] = base + "/revoke"
            if self._failures.get("discovery") == "issuer_mismatch":
                document["issuer"] = self._issuer + "/other"
            return JSONResponse(document)

    async def _jwks(self, request: Request) -> Response:
        with self._lock:
            failure = self._failure("jwks")
            if failure is not None:
                return failure
            return JSONResponse(
                {"keys": [_public_jwk(kid, key) for kid, key in self._keys.items()]}
            )

    async def _authorize(self, request: Request) -> Response:
        with self._lock:
            failure = self._failure("authorize")
            if failure is not None:
                return failure
            params = request.query_params
            redirect = params.get("redirect_uri", "")
            if params.get("client_id") != self._client_id or not _loopback_redirect(redirect):
                return _error("invalid_request")
            result = {"state": params.get("state", ""), "iss": self._issuer}
            challenge = params.get("code_challenge", "")
            if not challenge or params.get("code_challenge_method") != "S256":
                result["error"] = "invalid_request"
            elif self._authorize_error is not None:
                result["error"] = self._authorize_error
            else:
                code = token_urlsafe(24)
                self._codes[code] = _Code(
                    self._login_as,
                    redirect,
                    challenge,
                    params.get("nonce"),
                    params.get("scope", ""),
                    self._clock.now() + timedelta(seconds=60),
                )
                result["code"] = code
            separator = "&" if urlsplit(redirect).query else "?"
            return RedirectResponse(redirect + separator + urlencode(result), status_code=302)

    async def _device(self, request: Request) -> Response:
        form = await _form(request)
        with self._lock:
            failure = self._failure("device")
            if failure is not None:
                return failure
            if form.get("client_id") != self._client_id:
                return _error("invalid_client", 401)
            challenge = form.get("code_challenge", "")
            if not challenge or form.get("code_challenge_method") != "S256":
                return _error("invalid_request")
            code = token_urlsafe(24)
            user = token_hex(4).upper()
            user_code = user[:4] + "-" + user[4:]
            grant = _Device(
                challenge,
                form.get("scope", ""),
                self._clock.now() + self._device_ttl,
                self._interval,
            )
            self._devices[code] = grant
            self._user_codes[user_code] = grant
            uri = self._issuer + "/device"
            return JSONResponse(
                {
                    "device_code": code,
                    "user_code": user_code,
                    "verification_uri": uri,
                    "verification_uri_complete": uri + "?" + urlencode({"user_code": user_code}),
                    "expires_in": int(self._device_ttl.total_seconds()),
                    "interval": self._interval,
                }
            )

    async def _token(self, request: Request) -> Response:
        form = await _form(request)
        with self._lock:
            failure = self._failure("token")
            if failure is not None:
                return failure
            if form.get("client_id") != self._client_id:
                return _error("invalid_client", 401)
            grant_type = form.get("grant_type")
            if grant_type == "authorization_code":
                return self._exchange_code(form)
            if grant_type == "refresh_token":
                return self._exchange_refresh(form)
            if grant_type == "urn:ietf:params:oauth:grant-type:device_code":
                return self._poll_device(form)
            return _error("unsupported_grant_type")

    def _exchange_code(self, form: Mapping[str, str]) -> Response:
        code = form.get("code", "")
        grant = self._codes.get(code)
        if (
            grant is None
            or self._clock.now() >= grant.expires
            or form.get("redirect_uri") != grant.redirect
            or not _pkce_matches(form.get("code_verifier", ""), grant.challenge)
        ):
            return _error("invalid_grant")
        del self._codes[code]
        return self._tokens(grant.username, grant.scope, nonce=grant.nonce)

    def _exchange_refresh(self, form: Mapping[str, str]) -> Response:
        token = form.get("refresh_token", "")
        family = self._refresh.get(token)
        if family is None or family.revoked:
            return _error("invalid_grant")
        if family.current != token:
            family.revoked = True
            return _error("invalid_grant")
        return self._tokens(family.username, family.scope, family=family)

    def _poll_device(self, form: Mapping[str, str]) -> Response:
        grant = self._devices.get(form.get("device_code", ""))
        if grant is None or grant.consumed:
            return _error("invalid_grant")
        now = self._clock.now()
        if self._device_steps:
            step = self._device_steps.popleft()
            grant.last_poll = now
            if isinstance(step, Approve):
                grant.username = step.username
            else:
                if step == "slow_down":
                    grant.interval += 5
                elif step == "access_denied":
                    grant.denied = True
                elif step == "expired_token":
                    grant.expires = now
                return _error(step)
        else:
            if now >= grant.expires:
                return _error("expired_token")
            if grant.denied:
                return _error("access_denied")
            previous = grant.last_poll
            grant.last_poll = now
            if previous is not None and (now - previous).total_seconds() < grant.interval:
                grant.interval += 5
                return _error("slow_down")
        if grant.username is None:
            return _error("authorization_pending")
        if not _pkce_matches(form.get("code_verifier", ""), grant.challenge):
            return _error("invalid_grant")
        grant.consumed = True
        return self._tokens(grant.username, grant.scope)

    def _tokens(
        self,
        username: str,
        scope: str,
        *,
        nonce: str | None = None,
        family: _RefreshFamily | None = None,
    ) -> Response:
        refresh = token_urlsafe(32)
        if family is None:
            family = _RefreshFamily(username, scope, refresh)
        family.current = refresh
        self._refresh[refresh] = family
        claims = {"nonce": nonce} if nonce is not None else {}
        return JSONResponse(
            {
                "access_token": token_urlsafe(32),
                "token_type": "Bearer",
                "expires_in": int(self._token_ttl.total_seconds()),
                "refresh_token": refresh,
                "id_token": self._sign_token(username, claims=claims),
                "scope": scope,
            }
        )

    async def _revoke(self, request: Request) -> Response:
        form = await _form(request)
        with self._lock:
            failure = self._failure("revoke")
            if failure is not None:
                return failure
            token = form.get("token", "")
            self._revoked.append(token)
            family = self._refresh.get(token)
            if family is not None:
                family.revoked = True
            return Response(status_code=200)
