"""``current_actor``: a Huron bearer token becomes the request's actor."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from huron.applications.api.dependencies import RuntimeDep
from huron.core.security.rbac import Actor
from huron.pkg.errors import Unauthenticated

__all__ = ["ActorDep", "bearer_token", "current_actor"]


async def current_actor(request: Request, runtime: RuntimeDep) -> Actor:
    """The actor named by the ``Authorization: Bearer`` Huron token."""
    token = bearer_token(request)
    if token is None:
        raise Unauthenticated("the request has no Huron bearer token")
    claims = (await runtime.verifier()).verify(token)
    return Actor(claims.sub, claims.name, frozenset(claims.groups))


def bearer_token(request: Request) -> str | None:
    """The token of the request's ``Authorization: Bearer`` header, not yet verified."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


ActorDep = Annotated[Actor, Depends(current_actor)]
