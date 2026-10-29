"""The OIDC discovery document other systems use to trust Huron tokens."""

from __future__ import annotations

from typing import Any

__all__ = ["discovery_document"]


def discovery_document(issuer: str) -> dict[str, Any]:
    """The ``/.well-known/openid-configuration`` body for ``issuer``."""
    base = issuer.rstrip("/")
    return {
        "issuer": issuer,
        "jwks_uri": f"{base}/jwks.json",
        "token_endpoint": f"{base}/api/v1/auth/exchange",
        "id_token_signing_alg_values_supported": ["ES256"],
        "subject_types_supported": ["public"],
        "response_types_supported": ["token"],
        "claims_supported": ["sub", "name", "groups", "iss", "aud", "iat", "exp", "jti"],
    }
