"""A fake company OIDC issuer: discovery, JWKS and signed ID tokens."""

import json
import time
from typing import Any
from urllib.parse import parse_qsl

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://idp.test/realms/company"
AUDIENCE = "huron-cli"


class FakeIssuer:
    """Signs RS256 ID tokens and serves the documents a verifier fetches."""

    def __init__(self, issuer: str = ISSUER, kid: str = "company-key-1") -> None:
        self.issuer = issuer
        self.kid = kid
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.requests: list[str] = []
        self.now: float | None = None
        self.user = "dave"
        self.pending = 0
        self.device_error: str | None = None
        self.codes: dict[str, str] = {}
        self.refresh_ok = True

    @property
    def private_pem(self) -> bytes:
        return self._key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "jwks_uri": f"{self.issuer}/protocol/openid-connect/certs",
            "device_authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth/device",
            "token_endpoint": f"{self.issuer}/protocol/openid-connect/token",
            "authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth",
        }

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": self.kid, "alg": "RS256", "use": "sig"})
        return {"keys": [jwk]}

    def sign(
        self,
        username: str,
        *,
        audience: str = AUDIENCE,
        expires_in: int = 300,
        now: float | None = None,
        **extra: Any,
    ) -> str:
        issued = int(now if now is not None else time.time())
        payload = {
            "iss": self.issuer,
            "aud": audience,
            "sub": f"sub-{username}",
            "preferred_username": username,
            "name": username.title(),
            "iat": issued,
            "exp": issued + expires_in,
            **extra,
        }
        return jwt.encode(payload, self.private_pem, algorithm="RS256", headers={"kid": self.kid})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        self.requests.append(url)
        endpoints = self.discovery()
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=endpoints)
        if url == endpoints["jwks_uri"]:
            return httpx.Response(200, json=self.jwks())
        if url == endpoints["device_authorization_endpoint"]:
            return httpx.Response(
                200,
                json={
                    "device_code": "device-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": f"{self.issuer}/device",
                    "interval": 1,
                    "expires_in": 600,
                },
            )
        if url == endpoints["token_endpoint"]:
            return self._token(dict(parse_qsl(request.content.decode())))
        return httpx.Response(404, json={"error": "not_found"})

    def tokens(self, user: str) -> dict[str, Any]:
        return {
            "id_token": self.sign(user, now=self.now),
            "refresh_token": f"refresh-{user}",
            "token_type": "Bearer",
        }

    def _token(self, form: dict[str, str]) -> httpx.Response:
        grant = form.get("grant_type")
        if grant == "urn:ietf:params:oauth:grant-type:device_code":
            if self.device_error:
                return httpx.Response(400, json={"error": self.device_error})
            if self.pending > 0:
                self.pending -= 1
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(200, json=self.tokens(self.user))
        if grant == "authorization_code":
            user = self.codes.get(form.get("code", ""))
            if user is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self.tokens(user))
        if grant == "refresh_token":
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            user = form.get("refresh_token", "").removeprefix("refresh-")
            return httpx.Response(200, json=self.tokens(user))
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
