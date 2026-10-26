"""An in-process company issuer with real signatures and controllable failures."""

from __future__ import annotations

from datetime import timedelta
from functools import cache
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from starlette.requests import Request

    from huron.core.foundation.clock import Clock
    from tests.fakes.ldap_groups import Identities

Endpoint = Literal["discovery", "jwks", "authorize", "token", "device", "revoke"]
IdpFailure = int | Literal["timeout", "unreachable", "malformed", "issuer_mismatch"]
SigningKey = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey


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
        path = urlsplit(issuer).path
        self._app = Starlette(
            routes=[
                Route(path + "/.well-known/openid-configuration", self._discovery),
                Route(path + "/protocol/openid-connect/certs", self._jwks),
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
