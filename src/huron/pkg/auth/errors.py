"""Stable authentication error codes shared by every credential resolver."""

from __future__ import annotations


class AuthError(Exception):
    code = "INVALID_CREDENTIAL"


class ApiKeyExpired(AuthError):
    code = "APIKEY_EXPIRED"


class ApiKeyRevoked(AuthError):
    code = "APIKEY_REVOKED"


__all__ = [
    "ApiKeyExpired",
    "ApiKeyRevoked",
    "AuthError",
]
