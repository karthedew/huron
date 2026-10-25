"""Resolve bearer credentials before trusted development headers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from huron.core.security.principal import Principal

from ..runtime import Runtime, credential_authentication


async def current_principal(request: Request, runtime: Runtime) -> Principal:
    """Resolve the request credential to a principal, or 401.

    Args:
        request: The request carrying Authorization or development identity headers.
        runtime: The credential stores, optional OIDC resolver and authentication settings.

    Returns:
        The authenticated principal with its authentication method.
    """
    authorization = request.headers.get("authorization")
    bearer_token = authorization.removeprefix("Bearer ").strip() if authorization else None
    resolved = await credential_authentication(runtime).resolve(
        bearer_token=bearer_token,
        development_headers={
            "x-huron-subject": request.headers.get("x-huron-subject", ""),
            "x-huron-groups": request.headers.get("x-huron-groups", ""),
        },
    )
    return resolved.actor


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
